<script setup lang="ts">
/**
 * Asking the office for something. The kind decides the form: a question is
 * just words; anything about money also asks what, how much, from whom and
 * out of which account.
 */
import { computed, reactive, ref } from 'vue'
import { useMutation } from '@tanstack/vue-query'

import { api, ApiError } from '../api/client'
import type { RequestDetail, RequestKind } from '../api/types'
import { COMPTES, parseAmount } from '../document-fields'
import { KIND_HINT, KIND_ICON, KIND_LABEL, KINDS } from '../requests'
import AppIcon from './AppIcon.vue'

const props = defineProps<{ initialKind?: RequestKind }>()
const emit = defineEmits<{ close: []; created: [request: RequestDetail] }>()

const form = reactive({
  kind: (props.initialKind ?? 'compra') as RequestKind,
  title: '',
  description: '',
  amount: '',
  proveidor: '',
  compte: '',
  needed_by: '',
})
const error = ref('')

const spending = computed(() => form.kind !== 'consulta')
const amountValue = computed(() => (form.amount.trim() ? parseAmount(form.amount) : null))
const amountInvalid = computed(() => form.amount.trim() !== '' && amountValue.value == null)

const TITLE_PLACEHOLDER: Record<RequestKind, string> = {
  compra: 'Ex.: Plastilina i cartolines per a P5',
  pressupost: 'Ex.: Sortida a Cosmocaixa, 4t',
  consulta: 'Ex.: Com justifico una compra a Amazon?',
  reemborsament: 'Ex.: Material de ciències comprat al súper',
}

const AMOUNT_LABEL: Record<RequestKind, string> = {
  compra: 'Import aproximat',
  pressupost: 'Import previst',
  consulta: '',
  reemborsament: 'Import pagat',
}

const create = useMutation({
  mutationFn: () =>
    api.createRequest({
      kind: form.kind,
      title: form.title,
      description: form.description,
      amount: spending.value ? (amountValue.value ?? null) : null,
      proveidor: spending.value ? form.proveidor : '',
      compte: spending.value ? form.compte : '',
      needed_by: form.needed_by || null,
    }),
  onSuccess: (request) => emit('created', request),
  onError: (err) => {
    error.value = err instanceof ApiError ? err.message : "No s'ha pogut enviar la sol·licitud."
  },
})

function submit() {
  if (amountInvalid.value) return
  error.value = ''
  create.mutate()
}
</script>

<template>
  <Teleport to="body">
    <div class="overlay" @click.self="emit('close')" @keydown.esc="emit('close')">
      <form class="dialog request-dialog" @submit.prevent="submit">
        <h2 class="dialog-title">Nova sol·licitud a secretaria</h2>

        <div class="kinds" role="radiogroup" aria-label="Què necessites?">
          <label v-for="kind in KINDS" :key="kind" class="kind" :class="{ on: form.kind === kind }">
            <input v-model="form.kind" class="sr-only" type="radio" name="kind" :value="kind" />
            <AppIcon :name="KIND_ICON[kind]" :size="16" />
            <span class="kind-label">{{ KIND_LABEL[kind] }}</span>
          </label>
        </div>
        <p class="hint kind-hint">{{ KIND_HINT[form.kind] }}</p>

        <label class="field">
          <span class="label">{{ form.kind === 'consulta' ? 'Pregunta' : 'Què és' }}</span>
          <input
            v-model="form.title"
            class="input"
            type="text"
            maxlength="255"
            :placeholder="TITLE_PLACEHOLDER[form.kind]"
            required
          />
        </label>

        <label class="field">
          <span class="label">{{ form.kind === 'consulta' ? 'Detalls' : 'Per a què' }}</span>
          <textarea
            v-model="form.description"
            class="textarea"
            rows="3"
            :placeholder="form.kind === 'consulta' ? 'Opcional' : 'Curs, activitat, per què cal…'"
          />
        </label>

        <div v-if="spending" class="grid">
          <label class="field">
            <span class="label">{{ AMOUNT_LABEL[form.kind] }}</span>
            <input
              v-model="form.amount"
              class="input input-mono"
              inputmode="decimal"
              placeholder="0,00 €"
              :aria-invalid="amountInvalid"
            />
            <span v-if="amountInvalid" class="hint error">No és un import vàlid.</span>
          </label>
          <label class="field">
            <span class="label">Proveïdor</span>
            <input v-model="form.proveidor" class="input" type="text" placeholder="Si el saps" />
          </label>
          <label class="field">
            <span class="label">Compte</span>
            <select v-model="form.compte" class="select">
              <option value="">No ho sé</option>
              <option v-for="option in COMPTES" :key="option" :value="option">{{ option }}</option>
            </select>
          </label>
          <label class="field">
            <span class="label">{{ form.kind === 'reemborsament' ? 'Data de la compra' : 'Per quan' }}</span>
            <input v-model="form.needed_by" class="input" type="date" />
          </label>
        </div>
        <p v-if="form.kind === 'reemborsament'" class="hint">
          Un cop enviada, hi podràs adjuntar el tiquet o la factura des de la mateixa sol·licitud.
        </p>

        <p v-if="error" class="notice notice-error">
          <AppIcon name="alert" :size="15" />
          <span>{{ error }}</span>
        </p>

        <div class="dialog-actions">
          <button class="btn btn-outline" type="button" @click="emit('close')">Cancel·la</button>
          <button class="btn btn-primary" type="submit" :disabled="create.isPending.value || amountInvalid">
            <AppIcon name="send" :size="14" />
            {{ create.isPending.value ? 'Enviant…' : 'Envia a secretaria' }}
          </button>
        </div>
      </form>
    </div>
  </Teleport>
</template>

<style scoped>
.request-dialog {
  width: min(560px, 100%);
  max-height: calc(100vh - 48px);
  overflow: auto;
}

.kinds {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 6px;
}

.kind {
  display: grid;
  justify-items: center;
  gap: 4px;
  padding: 10px 6px;
  border: 1px solid var(--line);
  border-radius: var(--r-md);
  background: var(--surface-0);
  color: var(--ink-500);
  cursor: pointer;
}

.kind:hover {
  border-color: var(--line-strong);
  color: var(--ink-700);
}

.kind.on {
  border-color: var(--accent-400);
  background: var(--accent-50);
  color: var(--accent-700);
}

.kind:focus-within {
  outline: 2px solid var(--accent-500);
  outline-offset: 1px;
}

.kind-label {
  font-size: var(--text-sm);
  font-weight: 600;
}

.kind-hint {
  margin-top: -4px;
}

.grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 12px;
}

.error {
  color: var(--danger-700);
}

@media (max-width: 520px) {
  .kinds,
  .grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}
</style>
