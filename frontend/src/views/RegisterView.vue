<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useMutation, useQuery, useQueryClient } from '@tanstack/vue-query'
import { RouterLink, useRouter } from 'vue-router'

import { api } from '../api/client'
import type { DocumentRecord, ExtractionStatus } from '../api/types'
import { useExtractionTracker } from '../composables/useExtractionTracker'
import {
  ESTATS_PAGAMENT,
  TIPUS_DOCUMENT,
  formatAmount,
  formatDate,
} from '../document-fields'
import AppIcon from '../components/AppIcon.vue'
import DocumentIntake from '../components/DocumentIntake.vue'
import ImageViewer from '../components/ImageViewer.vue'
import SyncPanel from '../components/SyncPanel.vue'
import StatusPill from '../components/StatusPill.vue'

const queryClient = useQueryClient()
const router = useRouter()
const { activeTrackedJobs, syncFromDocuments } = useExtractionTracker()

// IDs currently going through validation — drives faster polling while non-empty
const validatingIds = ref<string[]>([])
const refetchInterval = computed(() =>
  validatingIds.value.length > 0 || activeTrackedJobs.value.length > 0 ? 2000 : 15000,
)

const documentsQuery = useQuery({
  queryKey: ['documents'],
  queryFn: api.getDocuments,
  refetchInterval,
})

const documents = computed<DocumentRecord[]>(() => documentsQuery.data.value ?? [])

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
type Filter = 'all' | 'active' | 'needs_validation' | 'validated' | 'error' | 'outside'

const filter = ref<Filter>('all')
const tipus = ref('')
const pagament = ref('')
const search = ref('')

const IN_FLIGHT: ExtractionStatus[] = ['pending', 'processing', 'written_to_sheet']

function needsReview(record: DocumentRecord) {
  return !record.validat && Object.values(record.ai_hints).some((hint) => hint.review)
}

const stats = computed(() => ({
  total: documents.value.length,
  active: documents.value.filter((item) => IN_FLIGHT.includes(item.extraction_status)).length,
  review: documents.value.filter((item) => item.extraction_status === 'needs_validation').length,
  validated: documents.value.filter((item) => item.extraction_status === 'validated').length,
  outside: documents.value.filter((item) => item.sheet_state !== 'synced' && !IN_FLIGHT.includes(item.extraction_status)).length,
}))

const visible = computed(() => {
  const term = search.value.trim().toLowerCase()
  return documents.value.filter((item) => {
    const matchesFilter =
      filter.value === 'all' ||
      (filter.value === 'active' && IN_FLIGHT.includes(item.extraction_status)) ||
      (filter.value === 'outside' &&
        item.sheet_state !== 'synced' &&
        !IN_FLIGHT.includes(item.extraction_status)) ||
      item.extraction_status === filter.value
    if (!matchesFilter) return false
    if (tipus.value && item.tipus_document !== tipus.value) return false
    if (pagament.value === '—' ? item.pagament : pagament.value && item.pagament !== pagament.value)
      return false
    if (!term) return true
    return [
      item.num_factura,
      item.num_doc_intern,
      item.proveidor,
      item.descripcio,
      item.descripcio_compra,
      item.cif_proveidor,
      item.responsable_nom,
    ]
      .filter(Boolean)
      .some((field) => field.toLowerCase().includes(term))
  })
})

const visibleTotal = computed(() =>
  visible.value.reduce((sum, item) => sum + (item.import ?? 0), 0),
)

// ── Mutations ────────────────────────────────────────────────────────────────
function invalidate() {
  void queryClient.invalidateQueries({ queryKey: ['documents'] })
}

/** Sends app edits on and counts what the sheet has waiting. Once a minute. */
const syncStatus = useQuery({
  queryKey: ['sync-status'],
  queryFn: api.syncDocuments,
  refetchInterval: 60000,
})
const showSync = ref(false)

const syncSummary = computed(() => {
  const result = syncStatus.data.value
  if (!result) return ''
  if (!result.sheet_configured) return 'No hi ha cap full de càlcul configurat: tot es desa només al servidor.'
  if (result.error) return result.error
  if (!result.waiting) return 'El full està al dia.'
  return `El full té ${result.waiting} ${result.waiting === 1 ? 'canvi' : 'canvis'} per integrar${
    result.conflicts ? `, ${result.conflicts} amb conflicte` : ''
  }.`
})

function closeSync() {
  showSync.value = false
  void syncStatus.refetch()
  invalidate()
}

const validateMutation = useMutation({
  mutationFn: (id: string) => api.validateDocument(id),
  onMutate: (id) => {
    validatingIds.value = [...validatingIds.value, id]
  },
  onError: (_error, id) => {
    validatingIds.value = validatingIds.value.filter((item) => item !== id)
  },
  onSuccess: invalidate,
})

const pendingDelete = ref<DocumentRecord | null>(null)
const deleteError = ref('')

const deleteMutation = useMutation({
  mutationFn: (id: string) => api.deleteDocument(id),
  onSuccess: () => {
    pendingDelete.value = null
    deleteError.value = ''
    invalidate()
  },
  onError: (error) => {
    deleteError.value =
      error instanceof Error ? error.message : "No s'ha pogut esborrar. Torna-ho a provar."
  },
})

// ── Photo preview ────────────────────────────────────────────────────────────
const previewSrc = ref<string | null>(null)
const previewLoading = ref(false)

async function openPhoto(record: DocumentRecord) {
  if (!record.file_url) return
  previewLoading.value = true
  try {
    previewSrc.value = await api.getDocumentFileBlob(record.num_doc_intern)
  } finally {
    previewLoading.value = false
  }
}

function closePhoto() {
  if (previewSrc.value) URL.revokeObjectURL(previewSrc.value)
  previewSrc.value = null
}

function openRecord(record: DocumentRecord) {
  void router.push({ name: 'document', params: { internalDocNumber: record.num_doc_intern } })
}

const showUpload = ref(true)
</script>

<template>
  <div class="register">
    <header class="page-head">
      <div>
        <h1 class="page-title">Registre de documents comptables</h1>
        <p class="page-lead">
          Desat al servidor i sincronitzat amb el full de càlcul compartit.
          <span
            v-if="syncSummary"
            class="sync-note"
            :class="{
              bad: syncStatus.data.value?.error || !syncStatus.data.value?.sheet_configured,
              warn: syncStatus.data.value?.waiting,
            }"
          >
            {{ syncSummary }}
          </span>
        </p>
      </div>
      <div class="head-actions">
        <button
          class="btn btn-outline sync-button"
          type="button"
          title="Compara el full amb el registre i tria què s'integra"
          @click="showSync = true"
        >
          <AppIcon name="sheet" />
          Sincronització
          <span v-if="syncStatus.data.value?.waiting" class="sync-count">
            {{ syncStatus.data.value.waiting }}
          </span>
        </button>
        <button class="btn btn-primary" type="button" @click="showUpload = !showUpload">
          <AppIcon :name="showUpload ? 'close' : 'plus'" />
          {{ showUpload ? 'Amaga' : 'Afegeix documents' }}
        </button>
      </div>
    </header>

    <section class="stats" aria-label="Resum">
      <button class="stat" :class="{ on: filter === 'all' }" type="button" @click="filter = 'all'">
        <span class="stat-label">Total</span>
        <span class="stat-value">{{ stats.total }}</span>
      </button>
      <button class="stat" :class="{ on: filter === 'active' }" type="button" @click="filter = 'active'">
        <span class="stat-label">En curs</span>
        <span class="stat-value">{{ stats.active }}</span>
      </button>
      <button
        class="stat"
        :class="{ on: filter === 'needs_validation' }"
        type="button"
        @click="filter = 'needs_validation'"
      >
        <span class="stat-label">Per revisar</span>
        <span class="stat-value" :class="{ attention: stats.review > 0 }">{{ stats.review }}</span>
      </button>
      <button
        class="stat"
        :class="{ on: filter === 'validated' }"
        type="button"
        @click="filter = 'validated'"
      >
        <span class="stat-label">Validats</span>
        <span class="stat-value">{{ stats.validated }}</span>
      </button>
      <button
        class="stat"
        :class="{ on: filter === 'outside' }"
        type="button"
        title="Pendents d'escriure al full, o eliminats del full però conservats aquí"
        @click="filter = 'outside'"
      >
        <span class="stat-label">Fora del full</span>
        <span class="stat-value" :class="{ attention: stats.outside > 0 }">{{ stats.outside }}</span>
      </button>
    </section>

    <DocumentIntake v-if="showUpload" @uploaded="invalidate" />

    <section class="card">
      <div class="card-head list-head">
        <div class="filters">
          <input
            v-model="search"
            class="input search"
            type="search"
            placeholder="Cerca per proveïdor, número, descripció…"
            aria-label="Cerca documents"
          />
          <select v-model="tipus" class="select" aria-label="Filtra per tipus">
            <option value="">Tots els tipus</option>
            <option v-for="option in TIPUS_DOCUMENT" :key="option" :value="option">{{ option }}</option>
          </select>
          <select v-model="pagament" class="select" aria-label="Filtra per pagament">
            <option value="">Qualsevol pagament</option>
            <option v-for="option in ESTATS_PAGAMENT" :key="option" :value="option">{{ option }}</option>
            <option value="—">Sense indicar</option>
          </select>
        </div>
        <span class="count muted">
          {{ visible.length }}<template v-if="visible.length !== stats.total"> de {{ stats.total }}</template>
          · {{ formatAmount(visibleTotal) }}
        </span>
      </div>

      <p v-if="documentsQuery.isLoading.value" class="empty">Carregant el registre…</p>
      <p v-else-if="documentsQuery.isError.value" class="empty">
        <span class="notice notice-error">
          <AppIcon name="alert" :size="15" />
          <span>{{ (documentsQuery.error.value as Error).message }}</span>
        </span>
      </p>
      <p v-else-if="!documents.length" class="empty">
        Encara no hi ha cap document. Fes una foto o puja'n un per començar.
      </p>
      <p v-else-if="!visible.length" class="empty">Cap document coincideix amb aquest filtre.</p>

      <div v-else class="table-scroll">
        <table class="table">
          <thead>
            <tr>
              <th>Estat</th>
              <th>Document</th>
              <th>Proveïdor</th>
              <th>Data</th>
              <th class="num">Import</th>
              <th>Pagament</th>
              <th class="actions"><span class="sr-only">Accions</span></th>
            </tr>
          </thead>
          <tbody>
            <tr
              v-for="record in visible"
              :key="record.num_doc_intern"
              class="row"
              @click="openRecord(record)"
            >
              <td><StatusPill :status="record.extraction_status" /></td>
              <td>
                <RouterLink
                  class="ref"
                  :to="{ name: 'document', params: { internalDocNumber: record.num_doc_intern } }"
                  @click.stop
                >
                  <strong>
                    {{ record.num_factura || 'Sense número' }}
                    <span
                      v-if="needsReview(record)"
                      class="flag"
                      title="La IA no n'està segura: hi ha camps per revisar"
                    />
                  </strong>
                  <span class="sub muted" :title="record.num_doc_intern">
                    {{ record.tipus_document || 'Tipus per determinar' }}
                    <AppIcon
                      v-if="record.sheet_state !== 'synced' && !IN_FLIGHT.includes(record.extraction_status)"
                      name="sheet"
                      :size="11"
                      class="sheet-flag"
                      :title="
                        record.sheet_state === 'removed'
                          ? 'Eliminat del full; conservat aquí'
                          : 'Pendent d\'escriure al full'
                      "
                    />
                  </span>
                </RouterLink>
              </td>
              <td class="supplier">
                <span v-if="record.proveidor" class="truncate">{{ record.proveidor }}</span>
                <span v-else class="muted">—</span>
              </td>
              <td class="mono">{{ formatDate(record.data_factura) || '—' }}</td>
              <td class="num">{{ formatAmount(record.import) }}</td>
              <td>
                <span
                  v-if="record.pagament"
                  class="badge"
                  :class="record.pagament === 'Pagat' ? 'badge-olive' : record.pagament === 'Altres' ? 'badge-neutral' : 'badge-gold'"
                >
                  {{ record.pagament === 'Pendent de pagament' ? 'Pendent' : record.pagament }}
                </span>
                <span v-else class="muted">—</span>
              </td>
              <td class="actions" @click.stop>
                <div class="row-actions">
                  <button
                    v-if="record.file_url && record.source_file_type?.startsWith('image/')"
                    class="btn btn-ghost btn-icon btn-sm"
                    type="button"
                    title="Mostra l'original"
                    :disabled="previewLoading"
                    @click="openPhoto(record)"
                  >
                    <AppIcon name="image" />
                    <span class="sr-only">Mostra l'original</span>
                  </button>
                  <button
                    v-if="record.extraction_status === 'needs_validation'"
                    class="btn btn-sm validate"
                    type="button"
                    :disabled="validatingIds.includes(record.num_doc_intern)"
                    @click="validateMutation.mutate(record.num_doc_intern)"
                  >
                    <AppIcon name="check" />
                    {{ validatingIds.includes(record.num_doc_intern) ? 'Desant…' : 'Valida' }}
                  </button>
                  <button
                    class="btn btn-ghost btn-icon btn-sm delete"
                    type="button"
                    title="Esborra el document"
                    @click="
                      () => {
                        deleteError = ''
                        pendingDelete = record
                      }
                    "
                  >
                    <AppIcon name="trash" />
                    <span class="sr-only">Esborra</span>
                  </button>
                </div>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </section>

    <SyncPanel v-if="showSync" @close="closeSync" />

    <ImageViewer v-if="previewSrc" :src="previewSrc" alt="Document original" @close="closePhoto" />

    <Teleport to="body">
      <div v-if="pendingDelete" class="overlay" @click.self="pendingDelete = null">
        <div class="dialog" role="dialog" aria-modal="true">
          <h2 class="dialog-title">Vols esborrar aquest document?</h2>
          <p class="subtle">
            <strong>{{ pendingDelete.num_factura || pendingDelete.num_doc_intern }}</strong>
            s'esborrarà de l'aplicació, del full de càlcul i de Drive. Només en quedarà rastre a
            les còpies de seguretat.
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
              Cancel·la
            </button>
            <button
              class="btn btn-danger"
              type="button"
              :disabled="deleteMutation.isPending.value"
              @click="deleteMutation.mutate(pendingDelete.num_doc_intern)"
            >
              {{ deleteMutation.isPending.value ? 'Esborrant…' : 'Esborra' }}
            </button>
          </div>
        </div>
      </div>
    </Teleport>
  </div>
</template>

<style scoped>
.register {
  display: grid;
  /* minmax(0, …) lets the table scroll inside its card instead of widening
     the page past the viewport. */
  grid-template-columns: minmax(0, 1fr);
  gap: 16px;
  max-width: 1280px;
}

.head-actions {
  display: flex;
  gap: 8px;
}

.sync-note {
  margin-left: 6px;
  color: var(--olive-700);
}

.sync-note.bad {
  color: var(--danger-700);
}

.sync-note.warn {
  color: var(--gold-800);
}

.sync-button {
  position: relative;
}

.sync-count {
  min-width: 18px;
  height: 18px;
  padding: 0 5px;
  border-radius: var(--r-full);
  background: var(--accent-700);
  color: #fff;
  font-size: var(--text-xs);
  font-weight: 700;
  line-height: 18px;
  text-align: center;
}

/* ── Stats double as status filters ──────────────────────────────────────── */
.stats {
  display: grid;
  grid-template-columns: repeat(5, minmax(0, 1fr));
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

.filters .select {
  width: auto;
  min-width: 150px;
}

.search {
  max-width: 300px;
}

.count {
  font-size: var(--text-sm);
  font-variant-numeric: tabular-nums;
  white-space: nowrap;
}

.row {
  cursor: pointer;
}

.ref {
  display: grid;
  line-height: 1.35;
}

.ref strong {
  display: inline-flex;
  align-items: center;
  gap: 6px;
}

.ref:hover strong {
  color: var(--accent-700);
}

.ref .sub {
  white-space: nowrap;
  display: inline-flex;
  align-items: center;
  gap: 4px;
  font-size: var(--text-sm);
}

.flag {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: var(--gold-500);
  box-shadow: 0 0 0 2px var(--gold-100);
}

.sheet-flag {
  color: var(--accent-700);
}

.supplier {
  max-width: 210px;
}

.table td.mono {
  white-space: nowrap;
}

.supplier .truncate {
  display: block;
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

@media (max-width: 960px) {
  .stats {
    grid-template-columns: repeat(3, minmax(0, 1fr));
  }

  .filters {
    flex-direction: column;
  }

  .search,
  .filters .select {
    max-width: none;
    width: 100%;
  }

  .list-head {
    flex-direction: column;
    align-items: stretch;
  }
}

@media (max-width: 560px) {
  .stats {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .head-actions {
    width: 100%;
  }

  .head-actions .btn {
    flex: 1;
  }
}
</style>
