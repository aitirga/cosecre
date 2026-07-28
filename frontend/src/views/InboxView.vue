<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useMutation, useQuery, useQueryClient } from '@tanstack/vue-query'
import { RouterLink, useRoute } from 'vue-router'

import { api } from '../api/client'
import { DOCUMENT_CONFIG } from '../document-config'
import type { DocumentType, ExtractionStatus, InvoiceRecord } from '../api/types'
import { useExtractionTracker } from '../composables/useExtractionTracker'
import AppIcon from '../components/AppIcon.vue'
import InvoiceUploadCard from '../components/InvoiceUploadCard.vue'
import StatusPill from '../components/StatusPill.vue'

const queryClient = useQueryClient()
const route = useRoute()
const documentType = computed(() => route.meta.documentType as DocumentType)
const config = computed(() => DOCUMENT_CONFIG[documentType.value])
const { activeTrackedJobs, syncFromDocuments } = useExtractionTracker(documentType.value)

function formatAmount(value: number | null): string {
  if (value == null) return '—'
  return value.toLocaleString('ca-ES', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
}

// IDs currently going through validation — drives faster polling while non-empty
const validatingIds = ref<string[]>([])
const refetchInterval = computed(() =>
  validatingIds.value.length > 0 || activeTrackedJobs.value.length > 0 ? 2000 : 15000,
)

const documentsQuery = useQuery({
  queryKey: computed(() => ['documents', documentType.value]),
  queryFn: () => api.getDocuments(documentType.value),
  refetchInterval,
})

const documents = computed<InvoiceRecord[]>(() => documentsQuery.data.value ?? [])

// When a document under validation is no longer `needs_validation`, drop it
watch(documents, (updated) => {
  syncFromDocuments(updated)
  if (!validatingIds.value.length) return
  validatingIds.value = validatingIds.value.filter((id) => {
    const record = updated.find((item) => item.num_doc_intern === id)
    return !record || record.extraction_status === 'needs_validation'
  })
})

// ── Filtering ────────────────────────────────────────────────────────────────
type Filter = 'all' | 'active' | 'needs_validation' | 'validated' | 'error'

const filter = ref<Filter>('all')
const search = ref('')

const IN_FLIGHT: ExtractionStatus[] = ['pending', 'processing', 'written_to_sheet']

const stats = computed(() => ({
  total: documents.value.length,
  active: documents.value.filter((item) => IN_FLIGHT.includes(item.extraction_status)).length,
  review: documents.value.filter((item) => item.extraction_status === 'needs_validation').length,
  validated: documents.value.filter((item) => item.extraction_status === 'validated').length,
}))

const visible = computed(() => {
  const term = search.value.trim().toLowerCase()
  return documents.value.filter((item) => {
    const matchesFilter =
      filter.value === 'all' ||
      (filter.value === 'active' && IN_FLIGHT.includes(item.extraction_status)) ||
      item.extraction_status === filter.value
    if (!matchesFilter) return false
    if (!term) return true
    return [item.num_factura, item.num_doc_intern, item.proveidor, item.descripcio]
      .filter(Boolean)
      .some((field) => field.toLowerCase().includes(term))
  })
})

// ── Mutations ────────────────────────────────────────────────────────────────
function invalidate() {
  void queryClient.invalidateQueries({ queryKey: ['documents', documentType.value] })
}

const refreshMutation = useMutation({
  mutationFn: () => api.refreshDocuments(documentType.value),
  onSuccess: invalidate,
})

const validateMutation = useMutation({
  mutationFn: (id: string) => api.validateDocument(documentType.value, id),
  onMutate: (id) => {
    validatingIds.value = [...validatingIds.value, id]
  },
  onError: (_error, id) => {
    validatingIds.value = validatingIds.value.filter((item) => item !== id)
  },
  onSuccess: invalidate,
})

const pendingDelete = ref<InvoiceRecord | null>(null)
const deleteError = ref('')

const deleteMutation = useMutation({
  mutationFn: (id: string) => api.deleteDocument(documentType.value, id),
  onSuccess: () => {
    pendingDelete.value = null
    deleteError.value = ''
    invalidate()
  },
  onError: (error) => {
    deleteError.value = error instanceof Error ? error.message : 'Delete failed. Please try again.'
  },
})

// ── Photo preview ────────────────────────────────────────────────────────────
const previewSrc = ref<string | null>(null)
const previewLoading = ref(false)

async function openPhoto(record: InvoiceRecord) {
  if (!record.file_url) return
  previewLoading.value = true
  try {
    previewSrc.value = await api.getDocumentFileBlob(documentType.value, record.num_doc_intern)
  } finally {
    previewLoading.value = false
  }
}

function closePhoto() {
  if (previewSrc.value) URL.revokeObjectURL(previewSrc.value)
  previewSrc.value = null
}

const showUpload = ref(true)
</script>

<template>
  <div class="inbox">
    <header class="page-head">
      <div>
        <h1 class="page-title">{{ config.listTitle }}</h1>
        <p class="page-lead">{{ config.listHeading }}</p>
      </div>
      <div class="head-actions">
        <button
          class="btn btn-outline"
          type="button"
          :disabled="refreshMutation.isPending.value"
          title="Pull the latest rows from Google Sheets"
          @click="refreshMutation.mutate()"
        >
          <AppIcon name="refresh" :class="{ spin: refreshMutation.isPending.value }" />
          Refresh
        </button>
        <button class="btn btn-primary" type="button" @click="showUpload = !showUpload">
          <AppIcon :name="showUpload ? 'close' : 'plus'" />
          {{ showUpload ? 'Hide intake' : 'Add ' + config.plural }}
        </button>
      </div>
    </header>

    <section class="stats" aria-label="Summary">
      <button class="stat" :class="{ on: filter === 'all' }" type="button" @click="filter = 'all'">
        <span class="stat-label">Total</span>
        <span class="stat-value">{{ stats.total }}</span>
      </button>
      <button
        class="stat"
        :class="{ on: filter === 'active' }"
        type="button"
        @click="filter = 'active'"
      >
        <span class="stat-label">In flight</span>
        <span class="stat-value">{{ stats.active }}</span>
      </button>
      <button
        class="stat"
        :class="{ on: filter === 'needs_validation' }"
        type="button"
        @click="filter = 'needs_validation'"
      >
        <span class="stat-label">Needs review</span>
        <span class="stat-value" :class="{ attention: stats.review > 0 }">{{ stats.review }}</span>
      </button>
      <button
        class="stat"
        :class="{ on: filter === 'validated' }"
        type="button"
        @click="filter = 'validated'"
      >
        <span class="stat-label">Validated</span>
        <span class="stat-value">{{ stats.validated }}</span>
      </button>
    </section>

    <InvoiceUploadCard v-if="showUpload" :document-type="documentType" @uploaded="invalidate" />

    <section class="card">
      <div class="card-head list-head">
        <div class="filters">
          <input
            v-model="search"
            class="input search"
            type="search"
            :placeholder="`Search ${config.plural}, suppliers, references…`"
            :aria-label="`Search ${config.plural}`"
          />
          <select v-model="filter" class="select status-filter" aria-label="Filter by status">
            <option value="all">All statuses</option>
            <option value="active">In flight</option>
            <option value="needs_validation">Needs review</option>
            <option value="validated">Validated</option>
            <option value="error">Failed</option>
          </select>
        </div>
        <span class="count muted">
          {{ visible.length }}<template v-if="visible.length !== stats.total">
            of {{ stats.total }}</template
          >
        </span>
      </div>

      <p v-if="documentsQuery.isLoading.value" class="empty">Loading {{ config.plural }}…</p>
      <p v-else-if="documentsQuery.isError.value" class="empty">
        <span class="notice notice-error">
          <AppIcon name="alert" :size="15" />
          <span>{{ (documentsQuery.error.value as Error).message }}</span>
        </span>
      </p>
      <p v-else-if="!documents.length" class="empty">{{ config.emptyLead }}</p>
      <p v-else-if="!visible.length" class="empty">No {{ config.plural }} match this filter.</p>

      <div v-else class="table-scroll">
        <table class="table">
          <thead>
            <tr>
              <th>Status</th>
              <th>Reference</th>
              <th>Supplier</th>
              <th class="num">Amount</th>
              <th>Date</th>
              <th class="actions"><span class="sr-only">Actions</span></th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="record in visible" :key="record.num_doc_intern">
              <td><StatusPill :status="record.extraction_status" /></td>
              <td>
                <RouterLink
                  class="ref"
                  :to="{
                    name: config.detailRouteName,
                    params: { internalDocNumber: record.num_doc_intern },
                  }"
                >
                  <strong>{{ record.num_factura || 'Not extracted' }}</strong>
                  <span class="mono muted">{{ record.num_doc_intern }}</span>
                </RouterLink>
              </td>
              <td class="supplier">
                <span v-if="record.proveidor">{{ record.proveidor }}</span>
                <span v-else class="muted">—</span>
              </td>
              <td class="num">{{ formatAmount(record.import) }}</td>
              <td>{{ record.data_factura || '—' }}</td>
              <td class="actions">
                <div class="row-actions">
                  <button
                    v-if="record.file_url"
                    class="btn btn-ghost btn-icon btn-sm"
                    type="button"
                    title="View the original"
                    :disabled="previewLoading"
                    @click="openPhoto(record)"
                  >
                    <AppIcon name="image" />
                    <span class="sr-only">View the original</span>
                  </button>
                  <button
                    v-if="record.extraction_status === 'needs_validation'"
                    class="btn btn-sm validate"
                    type="button"
                    :disabled="validatingIds.includes(record.num_doc_intern)"
                    @click="validateMutation.mutate(record.num_doc_intern)"
                  >
                    <AppIcon name="check" />
                    {{ validatingIds.includes(record.num_doc_intern) ? 'Saving…' : 'Validate' }}
                  </button>
                  <RouterLink
                    class="btn btn-outline btn-sm"
                    :to="{
                      name: config.detailRouteName,
                      params: { internalDocNumber: record.num_doc_intern },
                    }"
                  >
                    Open
                  </RouterLink>
                  <button
                    class="btn btn-ghost btn-icon btn-sm delete"
                    type="button"
                    :title="`Delete this ${config.singular}`"
                    @click="
                      () => {
                        deleteError = ''
                        pendingDelete = record
                      }
                    "
                  >
                    <AppIcon name="trash" />
                    <span class="sr-only">Delete</span>
                  </button>
                </div>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </section>

    <Teleport to="body">
      <div v-if="previewSrc" class="overlay" @click.self="closePhoto">
        <div class="photo" role="dialog" aria-modal="true" aria-label="Document preview">
          <button class="btn btn-ghost btn-icon photo-close" type="button" @click="closePhoto">
            <AppIcon name="close" />
            <span class="sr-only">Close</span>
          </button>
          <img :src="previewSrc" :alt="`${config.singular} original`" />
        </div>
      </div>
    </Teleport>

    <Teleport to="body">
      <div v-if="pendingDelete" class="overlay" @click.self="pendingDelete = null">
        <div class="dialog" role="dialog" aria-modal="true">
          <h2 class="dialog-title">Delete this {{ config.singular }}?</h2>
          <p class="subtle">
            <strong>{{ pendingDelete.num_factura || pendingDelete.num_doc_intern }}</strong> will be
            removed from the app, from Google Sheets and from Drive. This cannot be undone.
          </p>
          <p v-if="deleteError" class="notice notice-error">
            <AppIcon name="alert" :size="15" />
            <span>{{ deleteError }}</span>
          </p>
          <div class="dialog-actions">
            <button
              class="btn btn-outline"
              type="button"
              :disabled="deleteMutation.isPending.value"
              @click="pendingDelete = null"
            >
              Cancel
            </button>
            <button
              class="btn btn-danger"
              type="button"
              :disabled="deleteMutation.isPending.value"
              @click="deleteMutation.mutate(pendingDelete.num_doc_intern)"
            >
              {{ deleteMutation.isPending.value ? 'Deleting…' : 'Delete' }}
            </button>
          </div>
        </div>
      </div>
    </Teleport>
  </div>
</template>

<style scoped>
.inbox {
  display: grid;
  gap: 16px;
  max-width: 1180px;
}

.head-actions {
  display: flex;
  gap: 8px;
}

/* ── Stats double as status filters ──────────────────────────────────────── */
.stats {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 8px;
}

.stat {
  display: grid;
  gap: 2px;
  padding: 10px 12px;
  text-align: left;
  background: var(--surface-0);
  border: 1px solid var(--line);
  border-radius: var(--r-lg);
  box-shadow: var(--shadow-xs);
  transition:
    border-color 0.12s ease,
    background-color 0.12s ease;
}

.stat:hover {
  border-color: var(--line-strong);
}

/* An outline, not a colour wash: a permanently tinted tile at the top of the
   page reads as an alert rather than as "this filter is on". */
.stat.on {
  border-color: var(--accent-500);
}

.stat-label {
  font-size: var(--text-xs);
  font-weight: 600;
  letter-spacing: 0.06em;
  text-transform: uppercase;
  color: var(--ink-400);
}

.stat-value {
  font-size: var(--text-xl);
  font-weight: 600;
  font-variant-numeric: tabular-nums;
  line-height: 1.15;
}

.stat-value.attention {
  color: var(--accent-700);
}

/* ── List ────────────────────────────────────────────────────────────────── */
.list-head {
  align-items: center;
}

.filters {
  display: flex;
  gap: 8px;
  flex: 1;
  min-width: 0;
}

.search {
  max-width: 320px;
}

.status-filter {
  width: auto;
  min-width: 150px;
}

.count {
  font-size: var(--text-sm);
  font-variant-numeric: tabular-nums;
  white-space: nowrap;
}

.ref {
  display: grid;
  line-height: 1.35;
}

.ref:hover strong {
  color: var(--accent-700);
}

.supplier {
  max-width: 260px;
}

.row-actions {
  display: inline-flex;
  align-items: center;
  gap: 4px;
}

.validate {
  background: var(--olive-100);
  border-color: var(--olive-200);
  color: var(--olive-700);
}

.validate:hover:not(:disabled) {
  background: var(--olive-200);
}

.delete:hover:not(:disabled) {
  background: var(--danger-100);
  color: var(--danger-700);
}

/* ── Preview ─────────────────────────────────────────────────────────────── */
.photo {
  position: relative;
  max-width: min(92vw, 900px);
  max-height: 88vh;
  border-radius: var(--r-xl);
  overflow: hidden;
  background: var(--ink-900);
  box-shadow: var(--shadow-lg);
}

.photo img {
  display: block;
  max-width: 100%;
  max-height: 88vh;
  object-fit: contain;
}

.photo-close {
  position: absolute;
  top: 8px;
  right: 8px;
  z-index: 1;
  background: rgba(255, 255, 255, 0.85);
  color: var(--ink-900);
}

.photo-close:hover {
  background: #fff;
}

@media (max-width: 860px) {
  .stats {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .filters {
    flex-direction: column;
  }

  .search,
  .status-filter {
    max-width: none;
    width: 100%;
  }

  .list-head {
    flex-direction: column;
    align-items: stretch;
  }
}
</style>
