<script setup lang="ts">
/**
 * Les meves factures: send an invoice or a ticket to the office — a PDF, or a
 * photo straight from the phone — and see where each one you sent is.
 */
import { computed, ref, watch } from 'vue'
import { useQuery, useQueryClient } from '@tanstack/vue-query'
import { RouterLink, useRoute } from 'vue-router'

import { api } from '../api/client'
import type { RequestSummary, Submission } from '../api/types'
import AppIcon from '../components/AppIcon.vue'
import DocumentIntake from '../components/DocumentIntake.vue'
import ImageViewer from '../components/ImageViewer.vue'
import SearchInput from '../components/SearchInput.vue'
import SortTh from '../components/SortTh.vue'
import { useExtractionTracker } from '../composables/useExtractionTracker'
import { useTableQuery } from '../composables/useTableQuery'
import { formatAmount, formatDate } from '../document-fields'
import { KIND_LABEL, OPEN_STATUSES } from '../requests'
import { SUBMISSION_STATUS } from '../submissions'

const route = useRoute()
const queryClient = useQueryClient()
const { activeTrackedJobs } = useExtractionTracker()

const submissionsQuery = useQuery({
  queryKey: ['submissions'],
  queryFn: api.mySubmissions,
  // Faster while something of theirs is still being read.
  refetchInterval: computed(() => (activeTrackedJobs.value.length ? 3000 : 30_000)),
})
const submissions = computed<Submission[]>(() => submissionsQuery.data.value ?? [])

/** Requests an invoice can answer: their own, about money, not closed. */
const requestsQuery = useQuery({ queryKey: ['requests'], queryFn: api.listRequests })
const linkable = computed<RequestSummary[]>(() =>
  (requestsQuery.data.value ?? []).filter(
    (r) => r.kind !== 'consulta' && (OPEN_STATUSES.includes(r.status) || r.status === 'aprovada'),
  ),
)
const requestId = ref<number | null>(null)
// Arriving from a request ("Adjunta la factura") pre-selects it.
watch(
  () => route.query.sol,
  (value) => {
    const id = Number(value)
    if (Number.isFinite(id) && id > 0) requestId.value = id
  },
  { immediate: true },
)

const table = useTableQuery({
  rows: submissions,
  sorts: {
    document: (s) => s.num_factura || s.proveidor || null,
    data: (s) => s.data_factura,
    import: (s) => s.import_value,
    estat: (s) => SUBMISSION_STATUS[s.status].label,
    enviada: (s) => s.created_at,
  },
  search: (s) => [s.num_factura, s.proveidor, s.tipus_document, s.request_code, formatAmount(s.import_value)],
  filters: {},
})

function refresh() {
  void queryClient.invalidateQueries({ queryKey: ['submissions'] })
  void queryClient.invalidateQueries({ queryKey: ['requests'] })
}

// ── The original, to check what was sent ────────────────────────────────────
const preview = ref<{ url: string; name: string } | null>(null)
async function openOriginal(item: Submission) {
  const url = await api.submissionFileUrl(item.num_doc_intern)
  if (item.source_file_type?.startsWith('image/')) {
    preview.value = { url, name: item.file_name ?? item.num_doc_intern }
  } else {
    window.open(url, '_blank', 'noopener')
  }
}
function closePreview() {
  if (preview.value) URL.revokeObjectURL(preview.value.url)
  preview.value = null
}

const highlighted = computed(() => (typeof route.query.doc === 'string' ? route.query.doc : null))
</script>

<template>
  <div class="invoices">
    <header class="page-head">
      <div>
        <h1 class="page-title">Les meves factures</h1>
        <p class="page-lead">
          Envia a secretaria les factures i els tiquets del que has comprat. La IA en llegeix les
          dades i secretaria les valida.
        </p>
      </div>
    </header>

    <DocumentIntake
      target="submission"
      :request-id="requestId"
      title="Envia una factura o un tiquet"
      hint="Un PDF o una foto per document. Des del mòbil, fes-hi la foto directament."
      @uploaded="refresh"
    >
      <template #head>
        <label v-if="linkable.length" class="link-request">
          <span class="label">Per a una sol·licitud</span>
          <select v-model="requestId" class="select">
            <option :value="null">Cap</option>
            <option v-for="item in linkable" :key="item.id" :value="item.id">
              {{ item.code }} · {{ KIND_LABEL[item.kind] }} · {{ item.title }}
            </option>
          </select>
        </label>
      </template>
    </DocumentIntake>

    <section class="card">
      <div class="card-head list-head">
        <h2 class="card-title">Enviades</h2>
        <SearchInput
          v-if="submissions.length > 5"
          v-model="table.search.value"
          class="search"
          placeholder="Cerca per proveïdor, número…"
        />
        <span class="count muted">{{ table.visible.value.length }}</span>
      </div>

      <p v-if="submissionsQuery.isLoading.value" class="empty">Carregant…</p>
      <p v-else-if="!submissions.length" class="empty">Encara no n'has enviat cap.</p>
      <div v-else class="table-scroll">
        <table class="table">
          <thead>
            <tr>
              <SortTh :table="table" sort-key="document">Document</SortTh>
              <SortTh :table="table" sort-key="data">Data</SortTh>
              <SortTh :table="table" sort-key="import" class="num">Import</SortTh>
              <SortTh :table="table" sort-key="estat">Estat</SortTh>
              <th>Sol·licitud</th>
              <SortTh :table="table" sort-key="enviada">Enviada</SortTh>
              <th class="actions"><span class="sr-only">Original</span></th>
            </tr>
          </thead>
          <tbody>
            <tr
              v-for="item in table.visible.value"
              :key="item.num_doc_intern"
              :class="{ current: item.num_doc_intern === highlighted }"
            >
              <td>
                <div class="doc">
                  <strong class="truncate">{{ item.proveidor || 'Proveïdor per llegir' }}</strong>
                  <span class="sub muted truncate">
                    {{ item.num_factura || 'Sense número' }}
                    <template v-if="item.tipus_document"> · {{ item.tipus_document }}</template>
                  </span>
                </div>
              </td>
              <td class="mono">{{ formatDate(item.data_factura) || '—' }}</td>
              <td class="num">{{ formatAmount(item.import_value) }}</td>
              <td>
                <span class="badge" :class="SUBMISSION_STATUS[item.status].tone">
                  <span v-if="['pending', 'processing', 'written_to_sheet'].includes(item.status)" class="badge-dot badge-dot-pulse" />
                  {{ SUBMISSION_STATUS[item.status].label }}
                </span>
              </td>
              <td>
                <RouterLink
                  v-if="item.request_id"
                  class="request-link mono"
                  :to="{ name: 'requests', query: { sol: String(item.request_id) } }"
                >
                  {{ item.request_code }}
                </RouterLink>
                <span v-else class="muted">—</span>
              </td>
              <td class="muted nowrap">{{ item.created_at ? formatDate(item.created_at.slice(0, 10)) : '' }}</td>
              <td class="actions">
                <button
                  v-if="item.has_file"
                  class="btn btn-ghost btn-icon btn-sm"
                  type="button"
                  title="Mostra l'original"
                  @click="openOriginal(item)"
                >
                  <AppIcon :name="item.source_file_type?.startsWith('image/') ? 'image' : 'file'" />
                  <span class="sr-only">Mostra l'original</span>
                </button>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </section>

    <ImageViewer v-if="preview" :src="preview.url" :alt="preview.name" @close="closePreview" />
  </div>
</template>

<style scoped>
.invoices {
  display: grid;
  grid-template-columns: minmax(0, 1fr);
  gap: 16px;
}

.link-request {
  display: grid;
  gap: 3px;
  min-width: 0;
  max-width: 320px;
}

.list-head {
  align-items: center;
  gap: 10px;
}

.search {
  flex: 1 1 220px;
  max-width: 300px;
  margin-left: auto;
}

.count {
  font-size: var(--text-sm);
  font-variant-numeric: tabular-nums;
}

.doc {
  display: grid;
  min-width: 0;
  max-width: 320px;
  line-height: 1.35;
}

.sub {
  font-size: var(--text-sm);
}

.nowrap {
  white-space: nowrap;
}

tr.current td {
  background: var(--accent-50);
}

.request-link {
  font-size: var(--text-sm);
  color: var(--accent-700);
}
</style>
