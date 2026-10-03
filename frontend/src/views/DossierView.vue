<script setup lang="ts">
import { computed, ref } from 'vue'
import { useQuery } from '@tanstack/vue-query'
import { RouterLink } from 'vue-router'

import { api, ApiError } from '../api/client'
import type { ReconcileStatement } from '../api/types'
import { formatDate } from '../document-fields'
import { SOURCE_LABEL } from '../matching'
import AppIcon from '../components/AppIcon.vue'

/**
 * Eines → Dossier d'extracte. One PDF per statement: every line in an index,
 * then each justified payment beside its register entry and original — the
 * pile someone checking the accounts asks for, without opening forty files.
 * The hub builds it; this screen only picks the statement.
 */
const statementsQuery = useQuery({
  queryKey: ['reconcile-statements'],
  queryFn: api.reconcileStatements,
})
const statements = computed<ReconcileStatement[]>(() => statementsQuery.data.value ?? [])

const proposals = ref(false)
const building = ref<number | null>(null)
const error = ref('')

function period(s: ReconcileStatement) {
  if (!s.period_from) return '—'
  return s.period_from === s.period_to
    ? formatDate(s.period_from)
    : `${formatDate(s.period_from)} – ${formatDate(s.period_to)}`
}

function share(s: ReconcileStatement) {
  return s.payments ? Math.round((s.confirmed / s.payments) * 100) : 0
}

/** What the PDF will hold, in words: how many sheets it gets. */
function sheets(s: ReconcileStatement) {
  const count = s.confirmed + (proposals.value ? s.proposed : 0)
  return count === 1 ? '1 fitxa' : `${count} fitxes`
}

async function generate(statement: ReconcileStatement) {
  building.value = statement.id
  error.value = ''
  try {
    await api.downloadStatementDossier(statement, proposals.value)
  } catch (e) {
    error.value = e instanceof ApiError ? e.message : 'No s’ha pogut generar el dossier.'
  } finally {
    building.value = null
  }
}
</script>

<template>
  <div class="dossier">
    <header class="page-head">
      <div>
        <h1 class="page-title">Dossier d'extracte</h1>
        <p class="page-lead">
          Un PDF per extracte: primer l'índex de tots els moviments, amb el seu estat; després, per
          a cada pagament justificat, una fitxa amb el moviment, l'entrada del registre i la foto
          de la factura. Els originals en PDF s'hi afegeixen sencers.
        </p>
      </div>
    </header>

    <section class="card">
      <div class="card-head">
        <h2 class="card-title">Extractes</h2>
        <label class="toggle">
          <input v-model="proposals" type="checkbox" />
          <span>Inclou propostes sense confirmar</span>
          <span class="muted">— marcades com a proposta; per revisar, no per lliurar</span>
        </label>
      </div>

      <p v-if="error" class="notice notice-error inset">
        <AppIcon name="alert" :size="15" />
        <span>{{ error }}</span>
      </p>

      <p v-if="statementsQuery.isLoading.value" class="empty">Carregant…</p>
      <p v-else-if="!statements.length" class="empty">
        Encara no hi ha cap extracte. Puja'n un a
        <RouterLink :to="{ name: 'statements' }">Extractes</RouterLink>.
      </p>
      <div v-else class="table-scroll">
        <table class="table">
          <thead>
            <tr>
              <th>Compte</th>
              <th>Període</th>
              <th>Font</th>
              <th>Justificats</th>
              <th class="num">Per resoldre</th>
              <th class="actions"><span class="sr-only">Accions</span></th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="s in statements" :key="s.id">
              <td><strong>{{ s.compte }}</strong></td>
              <td class="mono">{{ period(s) }}</td>
              <td>
                {{ SOURCE_LABEL[s.source] ?? s.source }}
                <span class="sub muted truncate" :title="s.file_name">{{ s.file_name }}</span>
              </td>
              <td>
                <div class="progress">
                  <span class="count">{{ s.confirmed }} / {{ s.payments }}</span>
                  <span class="bar"><span :style="{ width: `${share(s)}%` }" /></span>
                </div>
              </td>
              <td class="num">
                <span :class="{ muted: !(s.unmatched + s.proposed) }">{{ s.unmatched + s.proposed }}</span>
              </td>
              <td class="actions">
                <div class="row-actions">
                  <span class="muted sheets">{{ sheets(s) }}</span>
                  <button
                    class="btn btn-outline btn-sm"
                    type="button"
                    :disabled="building !== null"
                    @click="generate(s)"
                  >
                    <AppIcon
                      :name="building === s.id ? 'refresh' : 'download'"
                      :size="13"
                      :class="{ spin: building === s.id }"
                    />
                    {{ building === s.id ? 'Generant…' : 'PDF' }}
                  </button>
                </div>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </section>
  </div>
</template>

<style scoped>
.dossier {
  display: grid;
  gap: 16px;
}

.toggle {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-size: var(--text-sm);
  cursor: pointer;
}

.inset {
  margin: 0 16px 12px;
}

.sub {
  display: block;
  max-width: 220px;
  font-size: var(--text-xs);
}

.progress {
  display: flex;
  align-items: center;
  gap: 8px;
}

.count {
  min-width: 52px;
  font-variant-numeric: tabular-nums;
}

.bar {
  width: 96px;
  height: 4px;
  border-radius: var(--r-full);
  background: var(--surface-2);
  overflow: hidden;
}

.bar span {
  display: block;
  height: 100%;
  background: var(--olive-700);
}

.row-actions {
  display: inline-flex;
  align-items: center;
  justify-content: flex-end;
  gap: 10px;
}

.sheets {
  font-size: var(--text-xs);
  white-space: nowrap;
}
</style>
