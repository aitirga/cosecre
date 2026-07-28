<script setup lang="ts">
import { computed, onUnmounted, reactive, ref, watch } from 'vue'
import { useMutation, useQuery, useQueryClient } from '@tanstack/vue-query'
import { RouterLink, useRoute } from 'vue-router'

import { api, ApiError } from '../api/client'
import { DOCUMENT_CONFIG } from '../document-config'
import { useExtractionTracker } from '../composables/useExtractionTracker'
import type { DocumentType } from '../api/types'
import AppIcon from '../components/AppIcon.vue'
import StatusPill from '../components/StatusPill.vue'

const route = useRoute()
const queryClient = useQueryClient()
const internalDocNumber = route.params.internalDocNumber as string
const documentType = computed(() => route.meta.documentType as DocumentType)
const config = computed(() => DOCUMENT_CONFIG[documentType.value])
const { getTrackedJob } = useExtractionTracker(documentType.value)

const documentQuery = useQuery({
  queryKey: computed(() => ['document', documentType.value, internalDocNumber]),
  queryFn: () => api.getDocument(documentType.value, internalDocNumber),
  refetchInterval: 10000,
})

const record = computed(() => documentQuery.data.value)

/** The nine sheet columns, in the order the spreadsheet uses. */
const FIELDS = [
  { key: 'num_factura', label: 'Núm. de la factura', type: 'text' },
  { key: 'data_factura', label: 'Data factura', type: 'text' },
  { key: 'proveidor', label: 'Proveïdor/a', type: 'text' },
  { key: 'cif_proveidor', label: 'CIF Proveïdor', type: 'text' },
  { key: 'import', label: 'Import', type: 'text' },
  { key: 'cif_proveit', label: 'CIF Proveït', type: 'text' },
  { key: 'pressupost_afectat', label: 'Pressupost afectat', type: 'text' },
  { key: 'adreca_proveidor', label: 'Adreça Proveïdor', type: 'area' },
  { key: 'descripcio', label: 'Descripció', type: 'area' },
] as const

type FieldKey = (typeof FIELDS)[number]['key']

const form = reactive<Record<FieldKey, string>>({
  num_factura: '',
  data_factura: '',
  proveidor: '',
  cif_proveidor: '',
  adreca_proveidor: '',
  import: '',
  cif_proveit: '',
  descripcio: '',
  pressupost_afectat: '',
})

/** True once the user has typed, so a background refetch cannot overwrite them. */
const dirty = ref(false)

watch(
  record,
  (value) => {
    if (!value || dirty.value) return
    form.num_factura = value.num_factura
    form.data_factura = value.data_factura
    form.proveidor = value.proveidor
    form.cif_proveidor = value.cif_proveidor
    form.adreca_proveidor = value.adreca_proveidor
    form.import = value.import != null ? String(value.import) : ''
    form.cif_proveit = value.cif_proveit
    form.descripcio = value.descripcio
    form.pressupost_afectat = value.pressupost_afectat
  },
  { immediate: true },
)

const saveError = ref('')
const validateError = ref('')
const saved = ref(false)

function invalidate() {
  void queryClient.invalidateQueries({
    queryKey: ['document', documentType.value, internalDocNumber],
  })
  void queryClient.invalidateQueries({ queryKey: ['documents', documentType.value] })
}

const saveMutation = useMutation({
  mutationFn: () => api.updateDocument(documentType.value, internalDocNumber, { ...form }),
  onSuccess: () => {
    saveError.value = ''
    dirty.value = false
    saved.value = true
    setTimeout(() => (saved.value = false), 2500)
    invalidate()
  },
  onError: (error) => {
    saveError.value = error instanceof ApiError ? error.message : 'Save failed. Please try again.'
  },
})

const validateMutation = useMutation({
  mutationFn: () => api.validateDocument(documentType.value, internalDocNumber),
  onSuccess: () => {
    validateError.value = ''
    invalidate()
  },
  onError: (error) => {
    validateError.value =
      error instanceof ApiError ? error.message : 'Validation failed. Please try again.'
  },
})

const trackedJob = computed(() => getTrackedJob(internalDocNumber))

// ── Original document preview ────────────────────────────────────────────────
const photoSrc = ref<string | null>(null)
const photoLoading = ref(false)

watch(
  record,
  async (value) => {
    if (!value?.file_url || photoSrc.value) return
    photoLoading.value = true
    try {
      photoSrc.value = await api.getDocumentFileBlob(documentType.value, internalDocNumber)
    } catch {
      // The preview is best-effort; the fields still work without it.
    } finally {
      photoLoading.value = false
    }
  },
  { immediate: true },
)

onUnmounted(() => {
  if (photoSrc.value) URL.revokeObjectURL(photoSrc.value)
})
</script>

<template>
  <div class="detail">
    <nav class="crumbs">
      <RouterLink :to="{ name: config.routeName }">{{ config.listTitle }}</RouterLink>
      <AppIcon name="chevron" :size="13" />
      <span class="mono muted">{{ internalDocNumber }}</span>
    </nav>

    <p v-if="documentQuery.isLoading.value" class="empty">Loading {{ config.singular }}…</p>
    <p v-else-if="documentQuery.isError.value" class="notice notice-error">
      <AppIcon name="alert" :size="15" />
      <span>{{ (documentQuery.error.value as Error).message }}</span>
    </p>

    <template v-else-if="record">
      <header class="page-head">
        <div>
          <h1 class="page-title">{{ record.num_factura || 'Not extracted yet' }}</h1>
          <p class="page-lead">
            {{ record.proveidor || 'Supplier unknown' }}
            <span v-if="record.source_file_name"> · {{ record.source_file_name }}</span>
          </p>
        </div>
        <StatusPill :status="record.extraction_status" />
      </header>

      <p v-if="record.error_message" class="notice notice-error">
        <AppIcon name="alert" :size="15" />
        <span>{{ record.error_message }}</span>
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
        <section class="card">
          <div class="card-head">
            <h2 class="card-title">Extracted fields</h2>
            <span v-if="saved" class="badge badge-olive">
              <AppIcon name="check" :size="12" />
              Saved
            </span>
          </div>

          <form class="card-body form" @submit.prevent="saveMutation.mutate()">
            <label v-for="field in FIELDS" :key="field.key" class="field" :class="field.type">
              <span class="label">{{ field.label }}</span>
              <textarea
                v-if="field.type === 'area'"
                v-model="form[field.key]"
                class="textarea"
                rows="3"
                @input="dirty = true"
              />
              <input
                v-else
                v-model="form[field.key]"
                class="input"
                type="text"
                @input="dirty = true"
              />
            </label>

            <div class="form-actions">
              <button
                class="btn btn-outline"
                type="submit"
                :disabled="saveMutation.isPending.value || !dirty"
              >
                {{ saveMutation.isPending.value ? 'Saving…' : 'Save changes' }}
              </button>
              <button
                class="btn btn-primary"
                type="button"
                :disabled="validateMutation.isPending.value || record.validat"
                @click="validateMutation.mutate()"
              >
                <AppIcon name="check" />
                {{
                  record.validat
                    ? 'Validated'
                    : validateMutation.isPending.value
                      ? 'Validating…'
                      : 'Validate'
                }}
              </button>
            </div>

            <p v-if="saveError" class="notice notice-error form-full">
              <AppIcon name="alert" :size="15" />
              <span>{{ saveError }}</span>
            </p>
            <p v-if="validateError" class="notice notice-error form-full">
              <AppIcon name="alert" :size="15" />
              <span>{{ validateError }}</span>
            </p>
          </form>
        </section>

        <aside class="side">
          <section class="card">
            <div class="card-head"><h2 class="card-title">Original</h2></div>
            <div class="card-body preview">
              <p v-if="photoLoading" class="hint">Loading…</p>
              <img v-else-if="photoSrc" :src="photoSrc" :alt="`${config.singular} original`" />
              <p v-else class="hint">
                No local copy. PDFs and documents synced before this release open from Drive.
              </p>
              <a
                v-if="record.file_link && record.file_link.startsWith('http')"
                class="btn btn-outline btn-sm btn-block"
                :href="record.file_link"
                target="_blank"
                rel="noreferrer noopener"
              >
                <AppIcon name="external" />
                Open in Drive
              </a>
            </div>
          </section>

          <section class="card">
            <div class="card-head"><h2 class="card-title">Record</h2></div>
            <dl class="card-body meta">
              <dt>Reference</dt>
              <dd class="mono">{{ record.num_doc_intern }}</dd>
              <dt>Sheet row</dt>
              <dd class="mono">{{ record.sheet_row_ref ?? '—' }}</dd>
              <dt>Type</dt>
              <dd>{{ config.singular }}</dd>
              <dt>File</dt>
              <dd class="truncate">{{ record.source_file_name ?? '—' }}</dd>
            </dl>
          </section>
        </aside>
      </div>
    </template>
  </div>
</template>

<style scoped>
.detail {
  display: grid;
  gap: 16px;
  max-width: 1180px;
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
  grid-template-columns: minmax(0, 1fr) 300px;
  gap: 16px;
  align-items: start;
}

.side {
  display: grid;
  gap: 16px;
}

.form {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 12px;
}

.form .area {
  grid-column: 1 / -1;
}

.form-actions,
.form-full {
  grid-column: 1 / -1;
}

.form-actions {
  display: flex;
  gap: 8px;
  margin-top: 4px;
}

.preview {
  display: grid;
  gap: 10px;
  justify-items: center;
}

.preview img {
  display: block;
  max-width: 100%;
  max-height: 340px;
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

@media (max-width: 1020px) {
  .columns {
    grid-template-columns: minmax(0, 1fr);
  }
}

@media (max-width: 640px) {
  .form {
    grid-template-columns: minmax(0, 1fr);
  }
}
</style>
