<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, onUnmounted, reactive, ref, watch } from 'vue'
import { useMutation, useQuery, useQueryClient } from '@tanstack/vue-query'
import { RouterLink, useRoute } from 'vue-router'

import { api, ApiError } from '../api/client'
import type { DocumentRecord, DocumentUpdate } from '../api/types'
import { useExtractionTracker } from '../composables/useExtractionTracker'
import {
  SECTIONS,
  describeHint,
  formatAmount,
  formatDate,
  parseAmount,
  parseDate,
  type FieldDef,
  type FieldKey,
} from '../document-fields'
import AiTrace from '../components/AiTrace.vue'
import AppIcon from '../components/AppIcon.vue'
import ImageViewer from '../components/ImageViewer.vue'
import StatusPill from '../components/StatusPill.vue'

const route = useRoute()
const queryClient = useQueryClient()
const internalDocNumber = route.params.internalDocNumber as string
const { getTrackedJob } = useExtractionTracker()

const documentQuery = useQuery({
  queryKey: ['document', internalDocNumber],
  queryFn: () => api.getDocument(internalDocNumber),
  refetchInterval: 10000,
})

const record = computed(() => documentQuery.data.value)
const ALL_FIELDS = SECTIONS.flatMap((section) => section.fields)

// ── Form state: everything as the text a person types ───────────────────────
const form = reactive(Object.fromEntries(ALL_FIELDS.map((f) => [f.key, ''])) as Record<FieldKey, string>)

/** True once the user has typed, so a background refetch cannot overwrite them. */
const dirty = ref(false)

function toText(field: FieldDef, value: DocumentRecord[FieldKey]): string {
  if (value == null) return ''
  if (field.kind === 'date') return formatDate(value as string)
  if (field.kind === 'amount') return (value as number).toFixed(2).replace('.', ',')
  return String(value)
}

function fillForm(value: DocumentRecord) {
  for (const field of ALL_FIELDS) form[field.key] = toText(field, value[field.key])
}

watch(
  record,
  (value) => {
    if (value && !dirty.value) fillForm(value)
  },
  { immediate: true },
)

const errors = computed(() => {
  const found: Partial<Record<FieldKey, string>> = {}
  for (const field of ALL_FIELDS) {
    const text = form[field.key]
    if (field.kind === 'date' && parseDate(text) === undefined) {
      found[field.key] = 'Data no vàlida (dd/mm/aaaa)'
    } else if (field.kind === 'amount' && parseAmount(text) === undefined) {
      found[field.key] = 'No és un import'
    }
  }
  return found
})

const hasErrors = computed(() => Object.keys(errors.value).length > 0)

/** Only what actually changed is sent, so a sheet edit elsewhere is not undone. */
function changes(): DocumentUpdate {
  const current = record.value
  if (!current) return {}
  const patch: Record<string, unknown> = {}
  for (const field of ALL_FIELDS) {
    const text = form[field.key]
    let value: unknown = text.trim()
    if (field.kind === 'date') value = parseDate(text)
    else if (field.kind === 'amount') value = parseAmount(text)
    const before = current[field.key] ?? (field.kind === 'date' || field.kind === 'amount' ? null : '')
    if (value !== before) patch[field.key] = value
  }
  return patch as DocumentUpdate
}

const isPaymentOther = computed(() => form.pagament === 'Altres' || Boolean(form.pagament_observacions))

function visibleFields(fields: FieldDef[]) {
  return fields.filter((field) => field.key !== 'pagament_observacions' || isPaymentOther.value)
}

// ── Hints ────────────────────────────────────────────────────────────────────
function hintFor(key: FieldKey) {
  return record.value?.ai_hints[key]
}

const reviewCount = computed(() => {
  if (!record.value || record.value.validat) return 0
  return Object.values(record.value.ai_hints).filter((hint) => hint.review).length
})

// ── Saving ───────────────────────────────────────────────────────────────────
const saveError = ref('')
const sheetWarning = ref('')
const saved = ref(false)

function afterSave(updated: DocumentRecord) {
  saveError.value = ''
  sheetWarning.value = updated.error_message ?? ''
  dirty.value = false
  queryClient.setQueryData(['document', internalDocNumber], updated)
  fillForm(updated)
  saved.value = true
  window.setTimeout(() => (saved.value = false), 2500)
  void queryClient.invalidateQueries({ queryKey: ['documents'] })
}

function reportError(error: unknown) {
  saveError.value =
    error instanceof ApiError ? error.message : "No s'ha pogut desar. Torna-ho a provar."
}

const saveMutation = useMutation({
  mutationFn: (extra: DocumentUpdate = {}) =>
    api.updateDocument(internalDocNumber, { ...changes(), ...extra }),
  onSuccess: afterSave,
  onError: reportError,
})

function save() {
  if (hasErrors.value || saveMutation.isPending.value) return
  saveMutation.mutate({})
}

function saveAndValidate() {
  if (hasErrors.value || saveMutation.isPending.value) return
  saveMutation.mutate({ validat: true })
}

function onKeydown(event: KeyboardEvent) {
  if ((event.metaKey || event.ctrlKey) && event.key === 's') {
    event.preventDefault()
    if (dirty.value) save()
  }
}

onMounted(() => window.addEventListener('keydown', onKeydown))
onBeforeUnmount(() => window.removeEventListener('keydown', onKeydown))

const trackedJob = computed(() => getTrackedJob(internalDocNumber))
const inFlight = computed(() =>
  ['pending', 'processing', 'written_to_sheet'].includes(record.value?.extraction_status ?? ''),
)

// ── Original document preview ────────────────────────────────────────────────
const photoSrc = ref<string | null>(null)
const viewerOpen = ref(false)
const photoLoading = ref(false)
const isImage = computed(() => record.value?.source_file_type?.startsWith('image/') ?? false)

watch(
  record,
  async (value) => {
    if (!value?.file_url || photoSrc.value || !isImage.value) return
    photoLoading.value = true
    try {
      photoSrc.value = await api.getDocumentFileBlob(internalDocNumber)
    } catch {
      // The preview is best-effort; the fields still work without it.
    } finally {
      photoLoading.value = false
    }
  },
  { immediate: true },
)

async function openOriginal() {
  const url = await api.getDocumentFileBlob(internalDocNumber)
  window.open(url, '_blank', 'noopener')
}

onUnmounted(() => {
  if (photoSrc.value) URL.revokeObjectURL(photoSrc.value)
})

// ── Download the original ────────────────────────────────────────────────────
const downloading = ref(false)
const downloadError = ref('')
const fileExtension = computed(() => {
  const name = record.value?.file_name ?? record.value?.source_file_name ?? ''
  const dot = name.lastIndexOf('.')
  return dot > 0 ? name.slice(dot + 1).toUpperCase().slice(0, 4) : 'FIT'
})
const fileDetails = computed(() => {
  const size = record.value?.file_size
  const parts: string[] = []
  if (size != null) {
    parts.push(
      size < 1024 * 1024
        ? `${Math.max(1, Math.round(size / 1024))} kB`
        : `${(size / (1024 * 1024)).toLocaleString('ca-ES', { maximumFractionDigits: 1 })} MB`,
    )
  }
  if (record.value?.origen) parts.push(record.value.origen)
  return parts.join(' · ')
})

async function downloadOriginal() {
  downloading.value = true
  downloadError.value = ''
  try {
    await api.downloadDocumentFile(internalDocNumber, record.value?.file_name ?? internalDocNumber)
  } catch (e) {
    downloadError.value = e instanceof ApiError ? e.message : "No s'ha pogut descarregar."
  } finally {
    downloading.value = false
  }
}

const SHEET_STATE = {
  synced: { label: 'Al full', tone: 'badge-olive' },
  pending: { label: "Pendent d'escriure", tone: 'badge-gold' },
  removed: { label: 'Eliminat del full', tone: 'badge-danger' },
} as const
</script>

<template>
  <div class="detail">
    <nav class="crumbs">
      <RouterLink :to="{ name: 'register' }">Registre</RouterLink>
      <AppIcon name="chevron" :size="13" />
      <span class="mono muted">{{ internalDocNumber }}</span>
    </nav>

    <p v-if="documentQuery.isLoading.value" class="empty">Carregant el document…</p>
    <p v-else-if="documentQuery.isError.value" class="notice notice-error">
      <AppIcon name="alert" :size="15" />
      <span>{{ (documentQuery.error.value as Error).message }}</span>
    </p>

    <template v-else-if="record">
      <header class="page-head">
        <div>
          <h1 class="page-title">{{ record.num_factura || 'Sense número' }}</h1>
          <p class="page-lead">
            {{ record.proveidor || 'Proveïdor desconegut' }}
            <span v-if="record.tipus_document"> · {{ record.tipus_document }}</span>
            <span v-if="record.import != null"> · {{ formatAmount(record.import) }}</span>
          </p>
        </div>
        <div class="head-badges">
          <span class="badge" :class="SHEET_STATE[record.sheet_state].tone">
            <AppIcon name="sheet" :size="12" />
            {{ SHEET_STATE[record.sheet_state].label }}
          </span>
          <StatusPill :status="record.extraction_status" />
        </div>
      </header>

      <p v-if="record.error_message" class="notice notice-error">
        <AppIcon name="alert" :size="15" />
        <span>{{ record.error_message }}</span>
      </p>
      <p v-if="record.sheet_state === 'removed'" class="notice notice-info">
        <AppIcon name="sheet" :size="15" />
        <span>
          Algú ha esborrat aquesta fila del full de càlcul. El document es conserva aquí; si el
          deses, hi tornarà a aparèixer.
        </span>
      </p>
      <p v-if="reviewCount" class="notice review-notice">
        <AppIcon name="sparkles" :size="15" />
        <span>
          La IA no n'està segura en {{ reviewCount }}
          {{ reviewCount === 1 ? 'camp, marcat' : 'camps, marcats' }} en groc. Passa-hi el ratolí
          per veure per què. En validar el document, es donen per revisats.
        </span>
      </p>

      <section v-if="trackedJob && trackedJob.progress < 100" class="card progress-card">
        <div class="progress-top">
          <strong>{{ trackedJob.stageLabel }}</strong>
          <span class="muted mono">{{ trackedJob.progress }}%</span>
        </div>
        <div class="progress"><span :style="{ width: `${trackedJob.progress}%` }" /></div>
        <p class="hint">{{ trackedJob.detail }}</p>
      </section>

      <div class="columns">
        <form class="card form-card" @submit.prevent="save">
          <fieldset :disabled="inFlight" class="sections">
            <section v-for="section in SECTIONS" :key="section.id" class="section">
              <h2 class="section-title">{{ section.title }}</h2>
              <div class="grid">
                <label
                  v-for="field in visibleFields(section.fields)"
                  :key="field.key"
                  class="field"
                  :class="{
                    wide: field.wide,
                    review: hintFor(field.key)?.review && !record.validat,
                    invalid: errors[field.key],
                  }"
                >
                  <span class="label">
                    {{ field.label }}
                    <span
                      v-if="hintFor(field.key)"
                      class="ai-tag"
                      :class="{ warn: hintFor(field.key)?.review && !record.validat }"
                      :title="describeHint(hintFor(field.key)!)"
                    >
                      IA
                    </span>
                  </span>
                  <select
                    v-if="field.kind === 'choice'"
                    v-model="form[field.key]"
                    class="select"
                    @change="dirty = true"
                  >
                    <option value="">—</option>
                    <option v-for="option in field.options" :key="option" :value="option">
                      {{ option }}
                    </option>
                    <option
                      v-if="form[field.key] && !field.options?.includes(form[field.key])"
                      :value="form[field.key]"
                    >
                      {{ form[field.key] }}
                    </option>
                  </select>
                  <textarea
                    v-else-if="field.kind === 'area'"
                    v-model="form[field.key]"
                    class="textarea"
                    rows="2"
                    :placeholder="field.placeholder"
                    @input="dirty = true"
                  />
                  <input
                    v-else
                    v-model="form[field.key]"
                    class="input"
                    :class="{ 'input-mono': field.kind === 'code' || field.kind === 'date' || field.kind === 'amount' }"
                    type="text"
                    :inputmode="field.kind === 'amount' ? 'decimal' : field.kind === 'date' ? 'numeric' : undefined"
                    :placeholder="field.kind === 'date' ? 'dd/mm/aaaa' : field.placeholder"
                    @input="dirty = true"
                  />
                  <span v-if="errors[field.key]" class="field-error">{{ errors[field.key] }}</span>
                  <span
                    v-else-if="field.key === 'compte_corrent' && record.iban_valid === false && !dirty"
                    class="field-error"
                  >
                    El dígit de control no quadra: probablement hi ha un número mal llegit.
                  </span>
                </label>
              </div>
            </section>
          </fieldset>

          <div class="form-actions">
            <button
              class="btn btn-outline"
              type="submit"
              :disabled="saveMutation.isPending.value || !dirty || hasErrors || inFlight"
            >
              {{ saveMutation.isPending.value ? 'Desant…' : 'Desa' }}
            </button>
            <button
              class="btn btn-primary"
              type="button"
              :disabled="saveMutation.isPending.value || (record.validat && !dirty) || hasErrors || inFlight"
              @click="saveAndValidate"
            >
              <AppIcon name="check" />
              {{ record.validat && !dirty ? 'Validat' : dirty ? 'Desa i valida' : 'Valida' }}
            </button>
            <span v-if="saved" class="badge badge-olive">
              <AppIcon name="check" :size="12" />
              Desat
            </span>
            <span class="hint kbd-hint">⌘S / Ctrl+S per desar</span>
          </div>

          <p v-if="saveError" class="notice notice-error">
            <AppIcon name="alert" :size="15" />
            <span>{{ saveError }}</span>
          </p>
          <p v-if="sheetWarning" class="notice notice-info">
            <AppIcon name="sheet" :size="15" />
            <span>Desat al servidor. {{ sheetWarning }} Es tornarà a provar automàticament.</span>
          </p>
        </form>

        <aside class="side">
          <section class="card">
            <div class="card-head"><h2 class="card-title">Original</h2></div>
            <div class="card-body preview">
              <p v-if="photoLoading" class="hint">Carregant…</p>
              <button
                v-else-if="photoSrc"
                class="photo-button"
                type="button"
                title="Amplia la imatge"
                @click="viewerOpen = true"
              >
                <img :src="photoSrc" alt="Document original" />
                <span class="zoom-hint">
                  <AppIcon name="image" :size="12" />
                  Amplia
                </span>
              </button>
              <button
                v-else-if="record.file_url"
                class="btn btn-outline btn-sm btn-block"
                type="button"
                @click="openOriginal"
              >
                <AppIcon name="external" />
                Obre el fitxer
              </button>
              <p v-else class="hint">Aquest document no té còpia al servidor.</p>
              <div v-if="record.file_url" class="file-strip">
                <span class="file-glyph mono" aria-hidden="true">{{ fileExtension }}</span>
                <span class="file-meta">
                  <span class="file-name mono" :title="record.file_name ?? undefined">
                    {{ record.file_name ?? record.source_file_name }}
                  </span>
                  <span v-if="fileDetails" class="file-details">{{ fileDetails }}</span>
                </span>
                <button
                  class="btn btn-outline btn-sm"
                  type="button"
                  :disabled="downloading"
                  title="Descarrega el fitxer original"
                  @click="downloadOriginal"
                >
                  <AppIcon name="download" />
                  {{ downloading ? 'Baixant…' : 'Descarrega' }}
                </button>
              </div>
              <p v-if="downloadError" class="notice notice-error file-error">
                <AppIcon name="alert" :size="15" />
                <span>{{ downloadError }}</span>
              </p>
              <a
                v-if="record.drive_url"
                class="btn btn-outline btn-sm btn-block"
                :href="record.drive_url"
                target="_blank"
                rel="noreferrer noopener"
              >
                <AppIcon name="external" />
                Obre a Drive
              </a>
            </div>
          </section>

          <section class="card">
            <div class="card-head"><h2 class="card-title">Registre</h2></div>
            <dl class="card-body meta">
              <dt>Referència</dt>
              <dd class="mono">{{ record.num_doc_intern }}</dd>
              <dt>Foto o original</dt>
              <dd>{{ record.origen || '—' }}</dd>
              <dt>Fila del full</dt>
              <dd class="mono">{{ record.sheet_row_ref ?? '—' }}</dd>
              <template v-if="record.legacy_type">
                <dt>Procedència</dt>
                <dd>Migrat de «{{ record.legacy_type === 'invoice' ? 'Factures' : 'Tiquets' }}»</dd>
              </template>
              <dt>Fitxer</dt>
              <dd class="truncate">{{ record.source_file_name ?? '—' }}</dd>
            </dl>
          </section>

          <details v-if="record.transcripcio" class="card transcript">
            <summary class="card-head">
              <h2 class="card-title">Text del document</h2>
              <AppIcon name="chevron" :size="13" class="chev" />
            </summary>
            <pre class="card-body">{{ record.transcripcio }}</pre>
          </details>
        </aside>
      </div>

      <AiTrace v-if="record.ai_trace" :record="record" :trace="record.ai_trace" />

      <ImageViewer
        v-if="viewerOpen && photoSrc"
        :src="photoSrc"
        alt="Document original"
        downloadable
        @download="downloadOriginal"
        @close="viewerOpen = false"
      />
    </template>
  </div>
</template>

<style scoped>
.detail {
  display: grid;
  grid-template-columns: minmax(0, 1fr);
  gap: 16px;
  max-width: 1280px;
}

.crumbs {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: var(--text-sm);
  color: var(--ink-400);
}

.crumbs a:hover {
  color: var(--accent-700);
}

.head-badges {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-wrap: wrap;
}

.review-notice {
  background: var(--gold-100);
  border-color: var(--gold-200);
  color: var(--gold-800);
}

.progress-card {
  display: grid;
  gap: 7px;
  padding: 12px 14px;
}

.progress-top {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 12px;
  font-size: var(--text-base);
}

.columns {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 320px;
  gap: 16px;
  align-items: start;
}

.side {
  display: grid;
  gap: 16px;
  position: sticky;
  top: 16px;
}

/* ── Form ────────────────────────────────────────────────────────────────── */
.form-card {
  display: grid;
  gap: 12px;
  padding-bottom: 14px;
}

.sections {
  display: grid;
  margin: 0;
  padding: 0;
  border: 0;
  min-width: 0;
}

.section {
  padding: 14px 16px;
  border-bottom: 1px solid var(--line);
}

.section-title {
  margin: 0 0 10px;
  font-size: var(--text-xs);
  font-weight: 600;
  letter-spacing: 0.06em;
  text-transform: uppercase;
  color: var(--ink-400);
}

.grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  align-items: start;
  gap: 10px 12px;
}

.field.wide {
  grid-column: span 2;
}

.field .label {
  display: inline-flex;
  align-items: center;
  gap: 6px;
}

.ai-tag {
  padding: 0 4px;
  border-radius: var(--r-xs);
  border: 1px solid var(--line);
  font-size: 9px;
  font-weight: 700;
  letter-spacing: 0.04em;
  color: var(--ink-400);
  cursor: help;
}

.ai-tag.warn {
  border-color: var(--gold-200);
  background: var(--gold-100);
  color: var(--gold-800);
}

.field.review .input,
.field.review .select,
.field.review .textarea {
  border-color: var(--gold-500);
  background: #fffbf0;
}

.field.invalid .input {
  border-color: var(--danger-600);
}

.field-error {
  font-size: var(--text-sm);
  color: var(--danger-700);
}

.form-actions {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 0 16px;
}

.kbd-hint {
  margin-left: auto;
}

.form-card > .notice {
  margin: 0 16px;
}

/* ── Side ────────────────────────────────────────────────────────────────── */
.preview {
  display: grid;
  gap: 10px;
  justify-items: center;
}

.photo-button {
  position: relative;
  display: block;
  padding: 0;
  border: 0;
  background: none;
  cursor: zoom-in;
}

.photo-button .zoom-hint {
  position: absolute;
  right: 6px;
  bottom: 6px;
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 2px 7px;
  border-radius: var(--r-full);
  background: rgba(28, 25, 23, 0.72);
  color: #fff;
  font-size: var(--text-xs);
  font-weight: 600;
  opacity: 0;
  transition: opacity 0.12s ease;
}

.photo-button:hover .zoom-hint,
.photo-button:focus-visible .zoom-hint {
  opacity: 1;
}

@media (hover: none) {
  .photo-button .zoom-hint {
    opacity: 1;
  }
}

.file-strip {
  display: grid;
  grid-template-columns: auto minmax(0, 1fr) auto;
  align-items: center;
  gap: 10px;
  width: 100%;
  padding: 8px 8px 8px 10px;
  border: 1px solid var(--line);
  border-radius: var(--r-sm);
  background: var(--surface-2);
}

.file-glyph {
  display: grid;
  place-items: center;
  width: 30px;
  height: 36px;
  border: 1px solid var(--line);
  border-radius: var(--r-xs);
  background: var(--surface-0);
  color: var(--ink-500);
  font-size: 9px;
  font-weight: 700;
  letter-spacing: 0.04em;
}

.file-meta {
  display: grid;
  min-width: 0;
  gap: 1px;
}

.file-name {
  overflow: hidden;
  font-size: var(--text-sm);
  color: var(--ink-700);
  text-overflow: ellipsis;
  white-space: nowrap;
}

.file-details {
  font-size: var(--text-xs);
  color: var(--ink-400);
}

.file-error {
  width: 100%;
}

.preview img {
  display: block;
  max-width: 100%;
  max-height: 420px;
  object-fit: contain;
  border-radius: var(--r-sm);
  background: var(--surface-2);
}

.meta {
  display: grid;
  grid-template-columns: auto minmax(0, 1fr);
  gap: 6px 14px;
  margin: 0;
  font-size: var(--text-base);
}

.meta dt {
  color: var(--ink-400);
}

.meta dd {
  margin: 0;
  min-width: 0;
}

.transcript summary {
  list-style: none;
  cursor: pointer;
}

.transcript summary::-webkit-details-marker {
  display: none;
}

.transcript .chev {
  transition: transform 0.12s ease;
}

.transcript[open] .chev {
  transform: rotate(90deg);
}

.transcript pre {
  margin: 0;
  max-height: 360px;
  overflow: auto;
  font-family: var(--font-mono);
  font-size: var(--text-sm);
  line-height: 1.45;
  white-space: pre-wrap;
  color: var(--ink-700);
}

@media (max-width: 1080px) {
  .columns {
    grid-template-columns: minmax(0, 1fr);
  }

  .side {
    position: static;
  }
}

@media (max-width: 640px) {
  .grid {
    grid-template-columns: minmax(0, 1fr);
  }

  .field.wide {
    grid-column: auto;
  }

  .kbd-hint {
    display: none;
  }
}
</style>
