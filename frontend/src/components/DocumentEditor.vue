<script setup lang="ts">
import { computed, defineAsyncComponent, onBeforeUnmount, onMounted, onUnmounted, reactive, ref, watch } from 'vue'
import { useMutation, useQuery, useQueryClient } from '@tanstack/vue-query'
import { RouterLink } from 'vue-router'

import { api, ApiError } from '../api/client'
import type { DocumentRecord, DocumentUpdate, Responsable } from '../api/types'
import { useExtractionTracker } from '../composables/useExtractionTracker'
import {
  SECTIONS,
  describeHint,
  formatAmount,
  formatDate,
  isResponsableEmail,
  parseAmount,
  parseDate,
  type FieldDef,
  type FieldKey,
} from '../document-fields'
import AiTrace from './AiTrace.vue'
import AppIcon from './AppIcon.vue'
import ImageViewer from './ImageViewer.vue'
import PersonInput from './PersonInput.vue'
import StatusPill from './StatusPill.vue'

// pdf.js is heavy, and only a PDF original needs it.
const PdfPreview = defineAsyncComponent(() => import('./PdfPreview.vue'))

/**
 * One document's fields, original and history: the whole of what a person
 * checks before validating it. The full page shows it on its own; the register
 * shows it in a window over the list (`embedded`), where the page header moves
 * to the window and the actions stay pinned at the bottom.
 *
 * The reference is read once: a parent showing another document gives this a
 * new `key` rather than a new prop, so no half-typed form leaks across.
 */
const props = defineProps<{
  internalDocNumber: string
  embedded?: boolean
  /** Offers "Valida i següent" when the window has somewhere to go next. */
  hasNext?: boolean
}>()
const emit = defineEmits<{ validated: [advance: boolean] }>()

const queryClient = useQueryClient()
const internalDocNumber = props.internalDocNumber
const { getTrackedJob } = useExtractionTracker()

const paymentsQuery = useQuery({
  queryKey: ['document-payments', internalDocNumber],
  queryFn: () => api.documentPayments(internalDocNumber),
})
const payments = computed(() => paymentsQuery.data.value ?? [])

const documentQuery = useQuery({
  queryKey: ['document', internalDocNumber],
  queryFn: () => api.getDocument(internalDocNumber),
  // Closer while the models read, so their fields land as soon as they are in.
  refetchInterval: (query) =>
    ['pending', 'processing', 'written_to_sheet'].includes(query.state.data?.extraction_status ?? '') ? 2000 : 10000,
})

const record = computed(() => documentQuery.data.value)
const ALL_FIELDS = SECTIONS.flatMap((section) => section.fields)

// ── Form state: everything as the text a person types ───────────────────────
const form = reactive(Object.fromEntries(ALL_FIELDS.map((f) => [f.key, ''])) as Record<FieldKey, string>)

/**
 * Fields typed and not yet saved. A background refetch refills every other
 * field, so the models finishing — or a sheet edit — shows up without
 * touching what is being typed.
 */
const unsaved = reactive(new Set<FieldKey>())
const dirty = computed(() => unsaved.size > 0)
/** Bumped on every keystroke, so a save only settles the fields it carried. */
const editVersion = ref(0)

function touch(...keys: FieldKey[]) {
  for (const key of keys) unsaved.add(key)
  editVersion.value += 1
}

function toText(field: FieldDef, value: DocumentRecord[FieldKey]): string {
  if (value == null) return ''
  if (field.kind === 'date') return formatDate(value as string)
  if (field.kind === 'amount') return (value as number).toFixed(2).replace('.', ',')
  return String(value)
}

function fillForm(value: DocumentRecord) {
  for (const field of ALL_FIELDS) {
    if (!unsaved.has(field.key)) form[field.key] = toText(field, value[field.key])
  }
}

watch(record, (value) => value && fillForm(value), { immediate: true })

const errors = computed(() => {
  const found: Partial<Record<FieldKey, string>> = {}
  for (const field of ALL_FIELDS) {
    const text = form[field.key]
    if (field.kind === 'date' && parseDate(text) === undefined) {
      found[field.key] = 'Data no vàlida (dd/mm/aaaa)'
    } else if (field.kind === 'amount' && parseAmount(text) === undefined) {
      found[field.key] = 'No és un import'
    } else if (field.kind === 'email' && text.trim() && !isResponsableEmail(text)) {
      found[field.key] = 'Només s\'accepten adreces @xtec.cat'
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
    let value: unknown = field.kind === 'person' ? text.trim().replace(/\s+/g, ' ') : text.trim()
    if (field.kind === 'email') value = (value as string).toLowerCase()
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

/** Choosing a known person fills the other half of the pair when it is empty. */
function pickResponsable(person: Responsable) {
  if (person.nom && !form.responsable_nom.trim()) form.responsable_nom = person.nom
  if (person.email && !form.responsable_email.trim()) form.responsable_email = person.email
  touch('responsable_nom', 'responsable_email')
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

function afterSave(updated: DocumentRecord, version: number) {
  saveError.value = ''
  sheetWarning.value = updated.error_message ?? ''
  // Typing that went on during the request is still unsaved, and stays put.
  if (version === editVersion.value) unsaved.clear()
  queryClient.setQueryData(['document', internalDocNumber], updated)
  saved.value = true
  window.setTimeout(() => (saved.value = false), 2500)
  void queryClient.invalidateQueries({ queryKey: ['documents'] })
}

function reportError(error: unknown) {
  saveError.value =
    error instanceof ApiError ? error.message : "No s'ha pogut desar. Torna-ho a provar."
}

const saveMutation = useMutation({
  mutationFn: async (extra: DocumentUpdate = {}) => {
    const version = editVersion.value
    return { updated: await api.updateDocument(internalDocNumber, { ...changes(), ...extra }), version }
  },
  onSuccess: ({ updated, version }) => afterSave(updated, version),
  onError: reportError,
})

function save() {
  if (hasErrors.value || saveMutation.isPending.value) return
  saveMutation.mutate({})
}

function saveAndValidate(advance = false) {
  if (hasErrors.value || saveMutation.isPending.value) return
  saveMutation.mutate({ validat: true }, { onSuccess: () => emit('validated', advance) })
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

// ── Filling in alongside the AI ──────────────────────────────────────────────
// While the models read, every field stays open. What a person types is saved
// on its own after a pause, and the hub leaves it standing when the reading
// lands; the fields still empty are the ones the AI is about to fill.
let autosaveTimer: number | undefined

watch(
  () => [editVersion.value, inFlight.value, saveMutation.isPending.value] as const,
  () => {
    window.clearTimeout(autosaveTimer)
    if (!inFlight.value || !dirty.value) return
    autosaveTimer = window.setTimeout(() => {
      if (inFlight.value && dirty.value && !hasErrors.value && !saveMutation.isPending.value) save()
    }, 700)
  },
)
onBeforeUnmount(() => window.clearTimeout(autosaveTimer))

/** Whose a field is: still being read, typed by the person, or neither. */
function ownerOf(field: FieldDef): 'reading' | 'mine' | null {
  if (inFlight.value) {
    if (form[field.key].trim()) return 'mine'
    return field.ai ? 'reading' : null
  }
  return field.key in kept.value ? 'mine' : null
}

/** The job poll can be a beat ahead of the entry; until the entry lands, it is still reading. */
const readingStage = computed(() => {
  const job = trackedJob.value
  if (job && job.progress < 100) return { label: job.stageLabel, progress: job.progress }
  return { label: job ? 'Acabant' : 'Llegint', progress: job ? 95 : 50 }
})

const readingCount = computed(() => ALL_FIELDS.filter((field) => ownerOf(field) === 'reading').length)
const mineCount = computed(() => ALL_FIELDS.filter((field) => ownerOf(field) === 'mine').length)

/** The register calls the amount `import`; the reading names it `import_value`. */
function readingKey(key: FieldKey) {
  return key === 'import' ? 'import_value' : key
}

/** What the models read for the fields a person had already filled in. */
const kept = computed(() => {
  const found: Partial<Record<FieldKey, string>> = {}
  const trace = record.value?.ai_trace?.kept ?? {}
  for (const field of ALL_FIELDS) {
    const value = trace[readingKey(field.key)]
    if (value == null || value === '') continue
    found[field.key] = toText(field, value as DocumentRecord[FieldKey])
  }
  return found
})

function useReading(field: FieldDef) {
  const value = kept.value[field.key]
  if (value == null) return
  form[field.key] = value
  touch(field.key)
}

/**
 * A field still holding what the AI wrote in it, until someone validates the
 * entry: violet, so the eye knows which values nobody has typed or checked
 * yet. Typing over one makes it the person's, and the colour goes.
 */
function aiFilled(field: FieldDef): boolean {
  const current = record.value
  if (!current || current.validat || inFlight.value) return false
  if (unsaved.has(field.key) || field.key in kept.value || !form[field.key].trim()) return false
  const hint = hintFor(field.key)
  // An unsure reading is flagged in gold instead.
  if (!hint || hint.source === 'migracio' || hint.review) return false
  const read = current.ai_trace?.final?.[readingKey(field.key)]
  return read ? toText(field, read.value as DocumentRecord[FieldKey]) === form[field.key] : true
}

const aiFilledCount = computed(() => ALL_FIELDS.filter((field) => aiFilled(field)).length)

/** The fields the reading just filled glow for a moment, so the eye finds them. */
const justFilled = reactive(new Set<string>())
watch(inFlight, (now, before) => {
  if (!before || now) return
  for (const key of record.value?.ai_trace?.filled ?? []) justFilled.add(key === 'import_value' ? 'import' : key)
  window.setTimeout(() => justFilled.clear(), 2400)
})

// ── Original document preview ────────────────────────────────────────────────
const photoSrc = ref<string | null>(null)
/** A PDF original, drawn beside the fields from the moment it is uploaded. */
const pdfSrc = ref<string | null>(null)
const viewerOpen = ref(false)
const photoLoading = ref(false)
const isImage = computed(() => record.value?.source_file_type?.startsWith('image/') ?? false)
const isPdf = computed(() => record.value?.source_file_type === 'application/pdf')

watch(
  record,
  async (value) => {
    if (!value?.file_url || photoSrc.value || pdfSrc.value || photoLoading.value) return
    if (!isImage.value && !isPdf.value) return
    photoLoading.value = true
    try {
      const url = await api.getDocumentFileBlob(internalDocNumber)
      if (isPdf.value) pdfSrc.value = url
      else photoSrc.value = url
    } catch {
      // The preview is best-effort; the fields still work without it.
    } finally {
      photoLoading.value = false
    }
  },
  { immediate: true },
)

async function openOriginal() {
  const url = pdfSrc.value ?? (await api.getDocumentFileBlob(internalDocNumber))
  window.open(url, '_blank', 'noopener')
}

onUnmounted(() => {
  if (photoSrc.value) URL.revokeObjectURL(photoSrc.value)
  if (pdfSrc.value) URL.revokeObjectURL(pdfSrc.value)
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

defineExpose({ dirty, viewerOpen })

const SHEET_STATE = {
  synced: { label: 'Al full', tone: 'badge-olive' },
  pending: { label: "Pendent d'escriure", tone: 'badge-gold' },
  removed: { label: 'Eliminat del full', tone: 'badge-danger' },
} as const
</script>

<template>
  <div class="editor" :class="{ embedded }">
    <p v-if="documentQuery.isLoading.value" class="empty">Carregant el document…</p>
    <p v-else-if="documentQuery.isError.value" class="notice notice-error">
      <AppIcon name="alert" :size="15" />
      <span>{{ (documentQuery.error.value as Error).message }}</span>
    </p>

    <template v-else-if="record">
      <header v-if="!embedded" class="page-head">
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
        <AppIcon name="sparkles" :size="15" class="ai-mark" />
        <span>
          La IA no n'està segura en {{ reviewCount }}
          {{ reviewCount === 1 ? 'camp, marcat' : 'camps, marcats' }} en groc. Passa-hi el ratolí
          per veure per què. En validar el document, es donen per revisats.
        </span>
      </p>

      <p v-if="!inFlight && aiFilledCount" class="notice ai-notice">
        <AppIcon name="sparkles" :size="15" class="ai-mark" />
        <span>
          {{ aiFilledCount }} {{ aiFilledCount === 1 ? 'camp l\'ha omplert' : 'camps els ha omplerts' }} la IA,
          en lila. Contrasta'ls amb l'original; en escriure-hi, passen a ser teus.
        </span>
      </p>

      <section v-if="inFlight" class="reading-card" aria-live="polite">
        <div class="reading-top">
          <AppIcon name="sparkles" :size="15" class="ai-mark" />
          <strong>{{ readingStage.label }}</strong>
          <span class="reading-counts">
            <span class="count-ai"><span class="dot" />{{ readingCount }} per la IA</span>
            <span class="count-mine"><span class="dot" />{{ mineCount }} teus</span>
          </span>
          <span class="mono reading-pct">{{ readingStage.progress }}%</span>
        </div>
        <div class="reading-bar"><span :style="{ width: `${readingStage.progress}%` }" /></div>
        <p class="reading-hint">
          La IA està omplint els camps marcats en lila. Mentrestant, omple el que vulguis: es desa
          sol i la IA no ho sobreescriurà.
        </p>
      </section>

      <div class="columns">
        <form class="card form-card" @submit.prevent="save">
          <fieldset class="sections">
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
                    reading: ownerOf(field) === 'reading',
                    mine: ownerOf(field) === 'mine',
                    'ai-filled': aiFilled(field),
                    filled: justFilled.has(field.key),
                  }"
                >
                  <span class="label">
                    {{ field.label }}
                    <span v-if="ownerOf(field) === 'reading'" class="ai-tag reading-tag" title="La IA està llegint aquest camp">
                      <span class="pulse" />IA
                    </span>
                    <span
                      v-else-if="ownerOf(field) === 'mine'"
                      class="mine-tag"
                      :title="inFlight ? 'L\'has omplert tu: la IA no el tocarà' : 'L\'has omplert tu mentre la IA llegia'"
                    >
                      Tu
                    </span>
                    <span
                      v-else-if="hintFor(field.key)"
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
                    @change="touch(field.key)"
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
                  <PersonInput
                    v-else-if="field.kind === 'person' || field.kind === 'email'"
                    v-model="form[field.key]"
                    :field="field.kind === 'person' ? 'nom' : 'email'"
                    :placeholder="ownerOf(field) === 'reading' ? 'La IA ho està llegint…' : field.placeholder"
                    @update:model-value="touch(field.key)"
                    @pick="pickResponsable"
                  />
                  <textarea
                    v-else-if="field.kind === 'area'"
                    v-model="form[field.key]"
                    class="textarea"
                    rows="2"
                    :placeholder="ownerOf(field) === 'reading' ? 'La IA ho està llegint…' : field.placeholder"
                    @input="touch(field.key)"
                  />
                  <input
                    v-else
                    v-model="form[field.key]"
                    class="input"
                    :class="{ 'input-mono': field.kind === 'code' || field.kind === 'date' || field.kind === 'amount' }"
                    type="text"
                    :inputmode="field.kind === 'amount' ? 'decimal' : field.kind === 'date' ? 'numeric' : undefined"
                    :placeholder="ownerOf(field) === 'reading' ? 'La IA ho està llegint…' : field.kind === 'date' ? 'dd/mm/aaaa' : field.placeholder"
                    @input="touch(field.key)"
                  />
                  <span v-if="errors[field.key]" class="field-error">{{ errors[field.key] }}</span>
                  <span v-else-if="!inFlight && kept[field.key] && kept[field.key] !== form[field.key]" class="kept-line">
                    <AppIcon name="sparkles" :size="11" class="ai-mark" />
                    <span class="truncate">La IA hi llegia <span class="mono">{{ kept[field.key] }}</span></span>
                    <button class="kept-use" type="button" @click.prevent="useReading(field)">Usa-ho</button>
                  </span>
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
            <span v-if="inFlight" class="autosave">
              <template v-if="saveMutation.isPending.value">Desant…</template>
              <template v-else-if="dirty">Es desarà en deixar d'escriure</template>
              <template v-else>Es desa sol mentre la IA llegeix</template>
            </span>
            <button
              v-else
              class="btn btn-outline"
              type="submit"
              :disabled="saveMutation.isPending.value || !dirty || hasErrors"
            >
              {{ saveMutation.isPending.value ? 'Desant…' : 'Desa' }}
            </button>
            <button
              class="btn btn-primary"
              type="button"
              :disabled="saveMutation.isPending.value || (record.validat && !dirty) || hasErrors || inFlight"
              :title="inFlight ? 'Espera que la IA acabi de llegir-lo' : undefined"
              @click="saveAndValidate()"
            >
              <AppIcon name="check" />
              {{ record.validat && !dirty ? 'Validat' : dirty ? 'Desa i valida' : 'Valida' }}
            </button>
            <button
              v-if="embedded && hasNext && !(record.validat && !dirty)"
              class="btn btn-outline"
              type="button"
              title="Valida aquest document i obre el següent de la llista"
              :disabled="saveMutation.isPending.value || hasErrors || inFlight"
              @click="saveAndValidate(true)"
            >
              Valida i següent
              <AppIcon name="chevron" :size="13" />
            </button>
            <span v-if="saved" class="badge badge-olive">
              <AppIcon name="check" :size="12" />
              Desat
            </span>
            <span v-if="!inFlight" class="hint kbd-hint">⌘S / Ctrl+S per desar</span>
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
              <PdfPreview v-else-if="pdfSrc" :src="pdfSrc" @open="openOriginal" />
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

          <section v-if="payments.length" class="card payments">
            <div class="card-head">
              <h2 class="card-title">Pagaments</h2>
            </div>
            <ul class="card-body payment-list">
              <li v-for="payment in payments" :key="payment.movement_id">
                <RouterLink :to="{ name: 'reconcile', query: { extracte: payment.import_id } }">
                  <strong>{{ formatDate(payment.data) }} · {{ formatAmount(payment.import_value) }}</strong>
                </RouterLink>
                <span class="muted">{{ payment.compte }} · {{ payment.tipus || 'mètode desconegut' }}</span>
                <span class="muted truncate">{{ payment.concepte }} {{ payment.mes_dades }}</span>
                <span class="badge" :class="payment.status === 'confirmed' ? 'badge-olive' : 'badge-gold'">
                  {{ payment.status === 'confirmed' ? 'Justificat' : `Proposat · ${payment.confidence}` }}
                </span>
              </li>
            </ul>
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
.editor {
  display: grid;
  grid-template-columns: minmax(0, 1fr);
  gap: 16px;
}

/* In the register's window the actions stay in reach however far the form
   scrolls: checking a field at the bottom should not mean scrolling back up
   to validate. */
.embedded .side {
  top: 0;
}

.embedded .form-card {
  padding-bottom: 0;
}

.embedded .form-actions {
  position: sticky;
  bottom: 0;
  z-index: 2;
  padding: 10px 16px;
  border-top: 1px solid var(--line);
  background: var(--surface-0);
}

.embedded .form-actions:last-child {
  border-radius: 0 0 var(--r-lg) var(--r-lg);
}

.embedded .form-card > .notice:last-child {
  margin-bottom: 12px;
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

.reading-card {
  display: grid;
  gap: 7px;
  margin-bottom: 12px;
  padding: 10px 12px;
  border: 1px solid var(--ai-200);
  border-radius: var(--r-md);
  background: var(--ai-50);
}

.reading-top {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: var(--text-base);
  color: var(--ai-800);
}

.reading-counts {
  display: inline-flex;
  gap: 10px;
  margin-left: auto;
  font-size: var(--text-sm);
  color: var(--ink-500);
}

.reading-counts .dot {
  display: inline-block;
  width: 7px;
  height: 7px;
  margin-right: 5px;
  border-radius: 50%;
  vertical-align: 1px;
}

.count-ai .dot {
  background: var(--ai-500);
}

.count-mine .dot {
  background: var(--accent-500);
}

.reading-pct {
  font-size: var(--text-xs);
  color: var(--ai-700);
  font-variant-numeric: tabular-nums;
}

.reading-bar {
  height: 3px;
  overflow: hidden;
  border-radius: 2px;
  background: var(--ai-100);
}

.reading-bar span {
  display: block;
  height: 100%;
  background: var(--ai-500);
  transition: width 0.4s ease;
}

.reading-hint {
  margin: 0;
  font-size: var(--text-sm);
  color: var(--ai-800);
  line-height: 1.45;
}

/* A value the AI wrote and nobody has checked yet. */
.field.ai-filled .input,
.field.ai-filled .select,
.field.ai-filled .textarea,
.field.ai-filled :deep(.input) {
  border-color: var(--ai-400);
  background: var(--ai-50);
  color: var(--ai-800);
}

.ai-notice {
  background: var(--ai-50);
  border-color: var(--ai-200);
  color: var(--ai-800);
}

/* A field the AI is reading: violet, with a slow sheen across it. */
.field.reading .input,
.field.reading .select,
.field.reading .textarea,
.field.reading :deep(.input) {
  border-color: var(--ai-200);
  background: linear-gradient(100deg, var(--ai-50) 30%, var(--ai-100) 50%, var(--ai-50) 70%) 0 0 / 300% 100%;
  animation: sheen 1.8s linear infinite;
}

.field.reading .input::placeholder,
.field.reading .textarea::placeholder,
.field.reading :deep(.input)::placeholder {
  color: var(--ai-400);
}

@keyframes sheen {
  from {
    background-position: 100% 0;
  }
  to {
    background-position: -50% 0;
  }
}

.field.mine .input,
.field.mine .select,
.field.mine .textarea,
.field.mine :deep(.input) {
  border-color: var(--accent-500);
}

.field.filled .input,
.field.filled .select,
.field.filled .textarea,
.field.filled :deep(.input) {
  animation: landed 2.4s ease-out;
}

@keyframes landed {
  from {
    background-color: var(--ai-100);
    border-color: var(--ai-400);
  }
}

.reading-tag {
  display: inline-flex;
  align-items: center;
  gap: 3px;
  cursor: default;
}

.pulse {
  width: 5px;
  height: 5px;
  border-radius: 50%;
  background: var(--ai-500);
  animation: pulse 1.1s ease-in-out infinite;
}

@keyframes pulse {
  50% {
    opacity: 0.25;
  }
}

.mine-tag {
  padding: 0 4px;
  border-radius: var(--r-xs);
  border: 1px solid var(--accent-200, var(--line));
  background: var(--accent-100);
  font-size: 9px;
  font-weight: 700;
  letter-spacing: 0.04em;
  color: var(--accent-700);
  cursor: help;
}

.kept-line {
  display: flex;
  align-items: center;
  gap: 5px;
  min-width: 0;
  font-size: var(--text-xs);
  color: var(--ai-700);
}

.kept-use {
  flex: none;
  padding: 0;
  border: 0;
  background: none;
  font: inherit;
  font-weight: 600;
  color: var(--ai-700);
  text-decoration: underline;
  cursor: pointer;
}

.autosave {
  font-size: var(--text-sm);
  color: var(--ink-500);
}

@media (prefers-reduced-motion: reduce) {
  .field.reading .input,
  .field.reading .select,
  .field.reading .textarea,
  .field.reading :deep(.input),
  .pulse {
    animation: none;
  }
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
  border: 1px solid var(--ai-200);
  background: var(--ai-50);
  font-size: 9px;
  font-weight: 700;
  letter-spacing: 0.04em;
  color: var(--ai-700);
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

.field.invalid .input,
.field.invalid :deep(.input) {
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
  background: rgba(27, 44, 70, 0.72);
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

.payment-list {
  display: grid;
  gap: 10px;
  margin: 0;
  list-style: none;
}

.payment-list li {
  display: grid;
  gap: 2px;
  font-size: var(--text-sm);
}

.payment-list .badge {
  justify-self: start;
}
</style>
