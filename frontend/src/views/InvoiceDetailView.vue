<script setup lang="ts">
import { computed, onUnmounted, reactive, ref, watch } from 'vue'
import { useMutation, useQuery, useQueryClient } from '@tanstack/vue-query'
import { useRoute } from 'vue-router'

import { api, ApiError } from '../api/client'
import { useExtractionTracker } from '../composables/useExtractionTracker'
import StatusPill from '../components/StatusPill.vue'

const route = useRoute()
const queryClient = useQueryClient()
const internalDocNumber = route.params.internalDocNumber as string
const { getTrackedJob } = useExtractionTracker()

const invoiceQuery = useQuery({
  queryKey: ['invoice', internalDocNumber],
  queryFn: () => api.getInvoice(internalDocNumber),
  refetchInterval: 10000,
})

const form = reactive({
  num_factura: '',
  data_factura: '',
  proveidor: '',
  cif_proveidor: '',
  adreca_proveidor: '',
  import: '' as string,
  cif_proveit: '',
  descripcio: '',
  pressupost_afectat: '',
})

watch(
  () => invoiceQuery.data.value,
  (invoice) => {
    if (!invoice) {
      return
    }
    form.num_factura = invoice.num_factura
    form.data_factura = invoice.data_factura
    form.proveidor = invoice.proveidor
    form.cif_proveidor = invoice.cif_proveidor
    form.adreca_proveidor = invoice.adreca_proveidor
    form.import = invoice.import != null ? String(invoice.import) : ''
    form.cif_proveit = invoice.cif_proveit
    form.descripcio = invoice.descripcio
    form.pressupost_afectat = invoice.pressupost_afectat
  },
  { immediate: true },
)

const saveError = ref('')
const validateError = ref('')

const saveMutation = useMutation({
  mutationFn: () => api.updateInvoice(internalDocNumber, { ...form }),
  onSuccess: () => {
    saveError.value = ''
    void queryClient.invalidateQueries({ queryKey: ['invoice', internalDocNumber] })
    void queryClient.invalidateQueries({ queryKey: ['invoices'] })
  },
  onError: (err) => {
    saveError.value = err instanceof ApiError ? err.message : 'Save failed. Please try again.'
  },
})

const validateMutation = useMutation({
  mutationFn: () => api.validateInvoice(internalDocNumber),
  onSuccess: () => {
    validateError.value = ''
    void queryClient.invalidateQueries({ queryKey: ['invoice', internalDocNumber] })
    void queryClient.invalidateQueries({ queryKey: ['invoices'] })
  },
  onError: (err) => {
    validateError.value = err instanceof ApiError ? err.message : 'Validation failed. Please try again.'
  },
})

const trackedJob = computed(() => getTrackedJob(internalDocNumber))

// Photo preview
const photoSrc = ref<string | null>(null)
const photoLoading = ref(false)

watch(
  () => invoiceQuery.data.value,
  async (invoice) => {
    if (!invoice?.file_url) return
    if (photoSrc.value) return  // already loaded
    photoLoading.value = true
    try {
      photoSrc.value = await api.getInvoiceFileBlob(internalDocNumber)
    } catch {
      // preview is best-effort
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
  <section class="detail-layout">
    <article class="panel detail-panel">
      <div v-if="invoiceQuery.isLoading.value" class="empty">Loading invoice...</div>
      <div v-else-if="invoiceQuery.isError.value" class="empty error">
        {{ (invoiceQuery.error.value as Error).message }}
      </div>
      <template v-else-if="invoiceQuery.data.value">
        <div class="header">
          <div>
            <p class="eyebrow">Invoice detail</p>
            <h2>{{ invoiceQuery.data.value.num_factura || invoiceQuery.data.value.num_doc_intern }}</h2>
            <p class="subtle">Internal reference {{ invoiceQuery.data.value.num_doc_intern }}</p>
          </div>
          <StatusPill :status="invoiceQuery.data.value.extraction_status" />
        </div>

        <section v-if="trackedJob" class="progress-card">
          <div class="progress-card__head">
            <div>
              <p class="eyebrow">Extraction progress</p>
              <strong>{{ trackedJob.stageLabel }}</strong>
            </div>
            <span>{{ trackedJob.progress }}%</span>
          </div>
          <div class="progress-track" aria-hidden="true">
            <span class="progress-value" :style="{ width: `${trackedJob.progress}%` }" />
          </div>
          <p class="subtle">{{ trackedJob.detail }}</p>
        </section>

        <div v-if="photoLoading" class="photo-preview photo-preview--loading">
          Loading photo…
        </div>
        <div v-else-if="photoSrc" class="photo-preview">
          <img :src="photoSrc" alt="Invoice photo" />
        </div>

        <form class="detail-form" @submit.prevent="saveMutation.mutate()">
          <label>
            <span>Núm. de la factura</span>
            <input v-model="form.num_factura" type="text" />
          </label>
          <label>
            <span>Data factura</span>
            <input v-model="form.data_factura" type="text" />
          </label>
          <label>
            <span>Proveïdor/a</span>
            <input v-model="form.proveidor" type="text" />
          </label>
          <label>
            <span>CIF Proveïdor</span>
            <input v-model="form.cif_proveidor" type="text" />
          </label>
          <label>
            <span>Adreça Proveïdor</span>
            <textarea v-model="form.adreca_proveidor" rows="3" />
          </label>
          <label>
            <span>Import</span>
            <input v-model="form.import" type="text" />
          </label>
          <label>
            <span>CIF Proveït</span>
            <input v-model="form.cif_proveit" type="text" />
          </label>
          <label>
            <span>Descripció</span>
            <textarea v-model="form.descripcio" rows="4" />
          </label>
          <label>
            <span>Pressupost afectat</span>
            <input v-model="form.pressupost_afectat" type="text" />
          </label>

          <div class="actions">
            <button class="ghost" type="submit" :disabled="saveMutation.isPending.value">
              {{ saveMutation.isPending.value ? 'Saving...' : 'Save changes' }}
            </button>
            <button
              class="primary"
              type="button"
              :disabled="validateMutation.isPending.value || invoiceQuery.data.value.validat"
              @click="validateMutation.mutate()"
            >
              {{
                invoiceQuery.data.value.validat
                  ? 'Already validated'
                  : validateMutation.isPending.value
                    ? 'Validating...'
                    : 'Validate in app and sheet'
              }}
            </button>
          </div>
          <p v-if="saveError" class="action-error">{{ saveError }}</p>
          <p v-if="validateError" class="action-error">{{ validateError }}</p>
        </form>
      </template>
    </article>
  </section>
</template>

<style scoped>
.detail-panel {
  padding: 24px;
}

.header {
  display: flex;
  justify-content: space-between;
  gap: 16px;
  align-items: flex-start;
  margin-bottom: 22px;
}

h2 {
  font-size: 2.4rem;
}

.detail-form {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 16px;
}

.progress-card {
  display: grid;
  gap: 10px;
  padding: 16px 18px;
  margin-bottom: 18px;
  border-radius: 18px;
  background: rgba(31, 55, 39, 0.05);
}

.progress-card__head {
  display: flex;
  justify-content: space-between;
  gap: 16px;
  align-items: baseline;
}

.progress-track {
  width: 100%;
  height: 10px;
  border-radius: 999px;
  overflow: hidden;
  background: rgba(49, 36, 29, 0.08);
}

.progress-value {
  display: block;
  height: 100%;
  border-radius: inherit;
  background: #f36a3e;
}

label {
  display: grid;
  gap: 8px;
}

textarea,
input {
  border: 1px solid var(--line);
  border-radius: 18px;
  padding: 0.95rem 1rem;
  background: white;
}

.actions {
  grid-column: 1 / -1;
  display: flex;
  gap: 12px;
  flex-wrap: wrap;
  margin-top: 12px;
}

.primary,
.ghost {
  border: 0;
  border-radius: 999px;
  padding: 0.9rem 1.1rem;
}

.primary {
  background: var(--accent);
  color: white;
}

.ghost {
  background: rgba(31, 55, 39, 0.08);
}

.subtle,
.eyebrow {
  color: var(--muted);
}

.empty {
  color: var(--muted);
}

.error {
  color: var(--danger);
}

.action-error {
  grid-column: 1 / -1;
  font-size: 0.88rem;
  color: var(--danger);
  padding: 10px 14px;
  background: rgba(188, 53, 53, 0.08);
  border-radius: 12px;
}

.photo-preview {
  border-radius: 18px;
  overflow: hidden;
  background: rgba(49, 36, 29, 0.05);
  margin-bottom: 18px;
  max-height: 420px;
  display: flex;
  align-items: center;
  justify-content: center;
}

.photo-preview img {
  display: block;
  max-width: 100%;
  max-height: 420px;
  object-fit: contain;
}

.photo-preview--loading {
  padding: 2rem;
  color: var(--muted);
  font-size: 0.9rem;
}

@media (max-width: 800px) {
  .detail-form {
    grid-template-columns: 1fr;
  }

  .header {
    flex-direction: column;
  }
}
</style>
