<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useMutation, useQuery, useQueryClient } from '@tanstack/vue-query'
import { RouterLink } from 'vue-router'

import { api } from '../api/client'
import type { InvoiceRecord } from '../api/types'
import { useExtractionTracker } from '../composables/useExtractionTracker'
import InvoiceUploadCard from '../components/InvoiceUploadCard.vue'
import StatusPill from '../components/StatusPill.vue'

function formatAmount(value: number | null): string {
  if (value == null) return '—'
  return value.toLocaleString('ca-ES', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
}

const queryClient = useQueryClient()
const { activeTrackedJobs, syncFromInvoices } = useExtractionTracker()

// IDs currently going through validation — drives faster polling while non-empty
const validatingIds = ref<string[]>([])
const refetchInterval = computed(() =>
  validatingIds.value.length > 0 || activeTrackedJobs.value.length > 0 ? 2000 : 15000,
)

const invoicesQuery = useQuery({
  queryKey: ['invoices'],
  queryFn: api.getInvoices,
  refetchInterval,
})

const invoices = computed<InvoiceRecord[]>(() => invoicesQuery.data.value ?? [])

// When an invoice under validation is no longer `needs_validation`, drop it from the set
watch(invoices, (updated) => {
  syncFromInvoices(updated)
  if (!validatingIds.value.length) return
  validatingIds.value = validatingIds.value.filter((id) => {
    const inv = updated.find((i) => i.num_doc_intern === id)
    return !inv || inv.extraction_status === 'needs_validation'
  })
})

const refreshMutation = useMutation({
  mutationFn: api.refreshInvoices,
  onSuccess: () => {
    void queryClient.invalidateQueries({ queryKey: ['invoices'] })
  },
})

const validateMutation = useMutation({
  mutationFn: api.validateInvoice,
  onMutate: (id) => {
    validatingIds.value = [...validatingIds.value, id]
  },
  onError: (_, id) => {
    validatingIds.value = validatingIds.value.filter((i) => i !== id)
  },
  onSuccess: () => {
    void queryClient.invalidateQueries({ queryKey: ['invoices'] })
  },
})

// ── Delete ────────────────────────────────────────────────────────────────────
const pendingDelete = ref<InvoiceRecord | null>(null)
const deleteError = ref('')

const deleteMutation = useMutation({
  mutationFn: (id: string) => api.deleteInvoice(id),
  onSuccess: () => {
    pendingDelete.value = null
    deleteError.value = ''
    void queryClient.invalidateQueries({ queryKey: ['invoices'] })
  },
  onError: (err) => {
    deleteError.value = err instanceof Error ? err.message : 'Delete failed. Please try again.'
  },
})

function requestDelete(invoice: InvoiceRecord) {
  deleteError.value = ''
  pendingDelete.value = invoice
}

function cancelDelete() {
  pendingDelete.value = null
  deleteError.value = ''
}

function confirmDelete() {
  if (pendingDelete.value) {
    deleteMutation.mutate(pendingDelete.value.num_doc_intern)
  }
}
// ─────────────────────────────────────────────────────────────────────────────

const stats = computed(() => ({
  total: invoices.value.length,
  pending: invoices.value.filter((invoice) =>
    ['pending', 'processing', 'written_to_sheet'].includes(invoice.extraction_status),
  ).length,
  review: invoices.value.filter((invoice) => invoice.extraction_status === 'needs_validation').length,
  validated: invoices.value.filter((invoice) => invoice.extraction_status === 'validated').length,
}))

function handleUploaded() {
  void queryClient.invalidateQueries({ queryKey: ['invoices'] })
}

// ── Photo preview ─────────────────────────────────────────────────────────────
const previewSrc = ref<string | null>(null)
const previewLoading = ref(false)

async function openPhoto(invoice: InvoiceRecord) {
  if (!invoice.file_url) return
  previewLoading.value = true
  try {
    previewSrc.value = await api.getInvoiceFileBlob(invoice.num_doc_intern)
  } finally {
    previewLoading.value = false
  }
}

function closePhoto() {
  if (previewSrc.value) URL.revokeObjectURL(previewSrc.value)
  previewSrc.value = null
}
// ─────────────────────────────────────────────────────────────────────────────
</script>

<template>
  <div class="inbox-layout">
    <section class="stats-bar">
      <article class="stat-card accent">
        <span class="stat-label">Total invoices</span>
        <strong class="stat-value">{{ stats.total }}</strong>
      </article>
      <article class="stat-card">
        <span class="stat-label">In flight</span>
        <strong class="stat-value">{{ stats.pending }}</strong>
      </article>
      <article class="stat-card">
        <span class="stat-label">Needs validation</span>
        <strong class="stat-value">{{ stats.review }}</strong>
      </article>
      <article class="stat-card">
        <span class="stat-label">Validated</span>
        <strong class="stat-value">{{ stats.validated }}</strong>
      </article>
    </section>

    <InvoiceUploadCard @uploaded="handleUploaded" />

    <section class="panel list-panel">
      <div class="section-head">
        <div>
          <p class="eyebrow">Invoices</p>
          <h2>Google Sheets backed invoice list</h2>
        </div>
        <button
          class="refresh-btn"
          type="button"
          :class="{ spinning: refreshMutation.isPending.value }"
          :disabled="refreshMutation.isPending.value"
          title="Refresh from Google Sheets"
          @click="refreshMutation.mutate()"
        >
          <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <path d="M3 12a9 9 0 1 0 9-9 9.75 9.75 0 0 0-6.74 2.74L3 8" />
            <path d="M3 3v5h5" />
          </svg>
        </button>
      </div>

      <p class="subtle">
        The app refreshes on a timer and can also be forced manually whenever someone edits the
        spreadsheet directly.
      </p>

      <div v-if="invoicesQuery.isLoading.value" class="empty-state">Loading invoices...</div>
      <div v-else-if="invoicesQuery.isError.value" class="empty-state error">
        {{ (invoicesQuery.error.value as Error).message }}
      </div>
      <div v-else-if="!invoices.length" class="empty-state">
        No invoices yet. Upload one to seed the sheet and the local job history.
      </div>
      <div v-else class="table-wrapper">
        <table>
          <thead>
            <tr>
              <th>Status</th>
              <th>Invoice</th>
              <th>Supplier</th>
              <th>Amount</th>
              <th>Date</th>
              <th />
            </tr>
          </thead>
          <tbody>
            <tr v-for="invoice in invoices" :key="invoice.num_doc_intern">
              <td><StatusPill :status="invoice.extraction_status" /></td>
              <td>
                <div class="cell-stack">
                  <strong>{{ invoice.num_factura || invoice.num_doc_intern }}</strong>
                  <span>{{ invoice.num_doc_intern }}</span>
                </div>
              </td>
              <td>{{ invoice.proveidor || 'Pending extraction' }}</td>
              <td>{{ formatAmount(invoice.import) }}</td>
              <td>{{ invoice.data_factura || '—' }}</td>
              <td class="actions-cell">
                <div class="row-actions">
                  <button
                    v-if="invoice.file_url"
                    class="btn-photo"
                    title="View photo"
                    :disabled="previewLoading"
                    @click="openPhoto(invoice)"
                  >
                    <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                      <path d="M23 19a2 2 0 0 1-2 2H3a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h4l2-3h6l2 3h4a2 2 0 0 1 2 2z" />
                      <circle cx="12" cy="13" r="4" />
                    </svg>
                  </button>
                  <button
                    v-if="invoice.extraction_status === 'needs_validation'"
                    class="btn-validate"
                    :class="{ 'btn-validate--checking': validatingIds.includes(invoice.num_doc_intern) }"
                    :disabled="validatingIds.includes(invoice.num_doc_intern)"
                    @click="validateMutation.mutate(invoice.num_doc_intern)"
                  >
                    <span v-if="validatingIds.includes(invoice.num_doc_intern)" class="dot-pulse" />
                    {{ validatingIds.includes(invoice.num_doc_intern) ? 'Checking…' : 'Validate' }}
                  </button>
                  <RouterLink
                    class="link-pill"
                    :to="{ name: 'invoice', params: { internalDocNumber: invoice.num_doc_intern } }"
                  >
                    Open
                  </RouterLink>
                  <button
                    class="btn-delete"
                    title="Delete invoice"
                    @click="requestDelete(invoice)"
                  >
                    <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                      <line x1="18" y1="6" x2="6" y2="18" />
                      <line x1="6" y1="6" x2="18" y2="18" />
                    </svg>
                  </button>
                </div>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </section>

    <section class="workspace-note">
      <div class="workspace-copy">
        <p class="eyebrow">Shared workspace</p>
        <h2>Capture, validate, and sync invoices without losing the thread.</h2>
      </div>
      <div class="workspace-steps">
        <article>
          <span>01</span>
          <strong>Drop in new files</strong>
          <p>Upload PDFs or snap a photo and the backend starts extraction immediately.</p>
        </article>
        <article>
          <span>02</span>
          <strong>Validate edge cases</strong>
          <p>Invoices that need attention stay visible in the queue until someone confirms them.</p>
        </article>
        <article>
          <span>03</span>
          <strong>Keep Sheets aligned</strong>
          <p>Use refresh whenever the spreadsheet changes outside the app and pull the latest state back in.</p>
        </article>
      </div>
    </section>

    <!-- Photo preview modal -->
    <Teleport to="body">
      <div v-if="previewSrc" class="dialog-overlay" @click.self="closePhoto">
        <div class="photo-dialog" role="dialog" aria-modal="true">
          <button class="photo-close" title="Close" @click="closePhoto">
            <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
              <line x1="18" y1="6" x2="6" y2="18" />
              <line x1="6" y1="6" x2="18" y2="18" />
            </svg>
          </button>
          <img :src="previewSrc" class="photo-img" alt="Invoice photo" />
        </div>
      </div>
    </Teleport>

    <!-- Delete confirmation dialog -->
    <Teleport to="body">
      <div v-if="pendingDelete" class="dialog-overlay" @click.self="cancelDelete">
        <div class="dialog" role="dialog" aria-modal="true">
          <p class="dialog-eyebrow">Delete invoice</p>
          <h3 class="dialog-title">
            {{ pendingDelete.num_factura || pendingDelete.num_doc_intern }}
          </h3>
          <p class="dialog-body">
            This will permanently remove the record from the app and from the Google Sheet. This
            action cannot be undone.
          </p>
          <p v-if="deleteError" class="dialog-error">{{ deleteError }}</p>
          <div class="dialog-actions">
            <button class="dialog-cancel" :disabled="deleteMutation.isPending.value" @click="cancelDelete">
              Cancel
            </button>
            <button class="dialog-confirm" :disabled="deleteMutation.isPending.value" @click="confirmDelete">
              {{ deleteMutation.isPending.value ? 'Deleting…' : 'Delete' }}
            </button>
          </div>
        </div>
      </div>
    </Teleport>
  </div>
</template>

<style scoped>
.inbox-layout {
  display: grid;
  gap: 20px;
}

.list-panel,
.table-wrapper {
  display: grid;
  gap: 18px;
}

.stats-bar {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 14px;
}

.stat-card {
  padding: 22px 24px;
  display: flex;
  flex-direction: column;
  gap: 6px;
  border-radius: 24px;
  background: rgba(255, 250, 242, 0.92);
  border: 1px solid rgba(49, 36, 29, 0.09);
  box-shadow: var(--shadow);
}

.accent {
  background: linear-gradient(135deg, rgba(243, 106, 62, 0.2) 0%, rgba(255, 205, 101, 0.14) 100%);
}

.stat-label {
  font-size: 0.78rem;
  font-weight: 600;
  letter-spacing: 0.1em;
  text-transform: uppercase;
  color: var(--muted);
}

.stat-value {
  font-family: var(--font-display);
  font-size: 2.4rem;
  line-height: 1;
  color: var(--ink);
}

.subtle,
.eyebrow,
.cell-stack span {
  color: var(--muted);
}

.list-panel {
  padding: 24px;
}

.workspace-note {
  display: grid;
  grid-template-columns: minmax(0, 1.1fr) minmax(0, 1.4fr);
  gap: 18px;
  padding: 18px 22px;
  border-radius: 20px;
  background:
    linear-gradient(135deg, rgba(31, 55, 39, 0.98), rgba(72, 101, 74, 0.92)),
    linear-gradient(180deg, rgba(255, 205, 101, 0.08), transparent);
  color: #fffaf2;
  box-shadow: var(--shadow);
}

.workspace-copy {
  display: grid;
  gap: 10px;
  align-content: start;
}

.workspace-copy .eyebrow {
  color: rgba(255, 250, 242, 0.72);
}

.workspace-copy h2 {
  font-size: clamp(1.1rem, 1.6vw, 1.4rem);
  font-weight: 600;
  max-width: 22ch;
  line-height: 1.4;
  opacity: 0.9;
}

.workspace-steps {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 12px;
}

.workspace-steps article {
  display: grid;
  gap: 6px;
  padding: 14px;
  border-radius: 14px;
  background: rgba(255, 248, 239, 0.08);
}

.workspace-steps span {
  font-size: 0.76rem;
  letter-spacing: 0.16em;
  text-transform: uppercase;
  color: rgba(255, 250, 242, 0.7);
}

.workspace-steps strong {
  font-size: 0.88rem;
  line-height: 1.2;
}

.workspace-steps p {
  color: rgba(255, 250, 242, 0.72);
  font-size: 0.82rem;
  line-height: 1.5;
}

.section-head {
  display: flex;
  justify-content: space-between;
  gap: 16px;
  align-items: flex-start;
}

h2 {
  font-size: 2rem;
}

.refresh-btn {
  width: 42px;
  height: 42px;
  border: 1px solid var(--line);
  border-radius: 999px;
  background: rgba(31, 55, 39, 0.06);
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  transition: background 0.15s;
}

.refresh-btn:hover:not(:disabled) {
  background: rgba(31, 55, 39, 0.12);
}

.refresh-btn svg {
  width: 17px;
  height: 17px;
}

.refresh-btn.spinning svg {
  animation: spin 0.8s linear infinite;
}

@keyframes spin {
  to { transform: rotate(-360deg); }
}

.link-pill {
  border: 1px solid var(--line);
  border-radius: 999px;
  background: rgba(31, 55, 39, 0.06);
  padding: 0.5rem 1rem;
  white-space: nowrap;
  font-size: 0.9rem;
  transition: background 0.15s;
}

.link-pill:hover {
  background: rgba(31, 55, 39, 0.12);
}

.btn-validate {
  border: 0;
  border-radius: 999px;
  background: rgba(72, 101, 74, 0.12);
  color: var(--olive);
  padding: 0.5rem 1rem;
  font-weight: 600;
  font-size: 0.9rem;
  white-space: nowrap;
  transition: background 0.15s;
}

.btn-validate:hover:not(:disabled) {
  background: rgba(72, 101, 74, 0.22);
}

.btn-validate--checking {
  opacity: 0.75;
  gap: 6px;
  display: inline-flex;
  align-items: center;
}

.btn-validate:disabled {
  cursor: default;
}

.dot-pulse {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: var(--olive);
  animation: pulse 1s ease-in-out infinite;
  flex-shrink: 0;
}

@keyframes pulse {
  0%, 100% { opacity: 1; transform: scale(1); }
  50% { opacity: 0.4; transform: scale(0.7); }
}

.actions-cell {
  text-align: right;
}

.row-actions {
  display: flex;
  gap: 8px;
  align-items: center;
  justify-content: flex-end;
}

.btn-delete {
  width: 34px;
  height: 34px;
  border: 1px solid rgba(49, 36, 29, 0.12);
  border-radius: 999px;
  background: transparent;
  display: flex;
  align-items: center;
  justify-content: center;
  color: var(--muted);
  transition: background 0.15s, color 0.15s, border-color 0.15s;
  flex-shrink: 0;
}

.btn-delete svg {
  width: 14px;
  height: 14px;
}

.btn-delete:hover {
  background: rgba(188, 53, 53, 0.08);
  color: var(--danger);
  border-color: rgba(188, 53, 53, 0.25);
}

.btn-photo {
  width: 34px;
  height: 34px;
  border: 1px solid rgba(49, 36, 29, 0.12);
  border-radius: 999px;
  background: transparent;
  display: flex;
  align-items: center;
  justify-content: center;
  color: var(--muted);
  transition: background 0.15s, color 0.15s, border-color 0.15s;
  flex-shrink: 0;
}

.btn-photo svg {
  width: 15px;
  height: 15px;
}

.btn-photo:hover:not(:disabled) {
  background: rgba(31, 55, 39, 0.08);
  color: var(--olive);
  border-color: rgba(31, 55, 39, 0.2);
}

.btn-photo:disabled {
  opacity: 0.5;
  cursor: default;
}

/* Photo preview dialog */
.photo-dialog {
  position: relative;
  max-width: min(90vw, 860px);
  max-height: 90vh;
  border-radius: 20px;
  overflow: hidden;
  background: rgba(30, 27, 24, 0.9);
  box-shadow: 0 32px 80px rgba(0, 0, 0, 0.5);
}

.photo-close {
  position: absolute;
  top: 12px;
  right: 12px;
  width: 34px;
  height: 34px;
  border: 0;
  border-radius: 999px;
  background: rgba(255, 250, 242, 0.15);
  display: flex;
  align-items: center;
  justify-content: center;
  color: #fffaf2;
  z-index: 1;
  transition: background 0.15s;
}

.photo-close:hover {
  background: rgba(255, 250, 242, 0.28);
}

.photo-close svg {
  width: 14px;
  height: 14px;
}

.photo-img {
  display: block;
  max-width: 100%;
  max-height: 90vh;
  object-fit: contain;
}

/* ── Delete confirmation dialog ────────────────────────────────────────────── */
.dialog-overlay {
  position: fixed;
  inset: 0;
  background: rgba(30, 27, 24, 0.45);
  backdrop-filter: blur(4px);
  -webkit-backdrop-filter: blur(4px);
  display: grid;
  place-items: center;
  z-index: 100;
}

.dialog {
  background: rgba(255, 250, 242, 0.98);
  border: 1px solid rgba(49, 36, 29, 0.1);
  border-radius: 24px;
  box-shadow: 0 32px 80px rgba(81, 49, 23, 0.22);
  padding: 32px;
  width: min(440px, calc(100vw - 32px));
  display: grid;
  gap: 12px;
}

.dialog-eyebrow {
  font-size: 0.78rem;
  font-weight: 600;
  letter-spacing: 0.1em;
  text-transform: uppercase;
  color: var(--muted);
}

.dialog-title {
  font-family: var(--font-display);
  font-size: 1.6rem;
  line-height: 1.1;
  margin: 0;
}

.dialog-body {
  color: var(--muted);
  font-size: 0.95rem;
  line-height: 1.55;
}

.dialog-actions {
  display: flex;
  gap: 10px;
  justify-content: flex-end;
  margin-top: 8px;
}

.dialog-cancel {
  border: 1px solid var(--line);
  border-radius: 999px;
  background: transparent;
  padding: 0.7rem 1.3rem;
  font-weight: 600;
  transition: background 0.15s;
}

.dialog-cancel:hover:not(:disabled) {
  background: rgba(31, 55, 39, 0.06);
}

.dialog-confirm {
  border: 0;
  border-radius: 999px;
  background: var(--danger);
  color: white;
  padding: 0.7rem 1.3rem;
  font-weight: 700;
  transition: opacity 0.15s;
}

.dialog-confirm:disabled,
.dialog-cancel:disabled {
  opacity: 0.5;
  cursor: default;
}

.dialog-error {
  font-size: 0.88rem;
  color: var(--danger);
  padding: 10px 14px;
  background: rgba(188, 53, 53, 0.08);
  border-radius: 12px;
}

table {
  width: 100%;
  border-collapse: collapse;
}

th,
td {
  padding: 0.95rem 0.75rem;
  text-align: left;
  border-bottom: 1px solid rgba(49, 36, 29, 0.08);
  vertical-align: middle;
}

th {
  font-size: 0.84rem;
  color: var(--muted);
  text-transform: uppercase;
  letter-spacing: 0.08em;
}

.cell-stack {
  display: grid;
}

.empty-state {
  padding: 1rem 0;
  color: var(--muted);
}

.error {
  color: var(--danger);
}

@media (max-width: 980px) {
  .stats-bar {
    grid-template-columns: repeat(2, 1fr);
  }

  .workspace-note {
    grid-template-columns: 1fr;
  }

  .workspace-copy h2 {
    max-width: 100%;
  }

  .workspace-steps {
    grid-template-columns: 1fr;
  }
}

@media (max-width: 520px) {
  .stats-bar {
    grid-template-columns: 1fr 1fr;
  }

  .stat-card {
    padding: 18px;
  }

  .stat-value {
    font-size: 2rem;
  }

  .workspace-note,
  .list-panel {
    padding: 20px;
  }
}

@media (max-width: 720px) {
  .table-wrapper {
    overflow-x: auto;
  }
}
</style>
