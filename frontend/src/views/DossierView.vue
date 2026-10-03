<script setup lang="ts">
import { computed, ref } from 'vue'
import { useQueries, useQuery } from '@tanstack/vue-query'
import { RouterLink } from 'vue-router'

import { api, ApiError } from '../api/client'
import type { Movement, ReconcileStatement } from '../api/types'
import { formatDate } from '../document-fields'
import { SOURCE_LABEL } from '../matching'
import AppIcon from '../components/AppIcon.vue'

/**
 * Eines → Dossier d'extracte. One PDF per statement: every line in an index,
 * then each justified payment beside its register entry and original — the
 * pile someone checking the accounts asks for, without opening forty files.
 * The hub builds it; this screen only picks the statement and, optionally,
 * the dates it should cover.
 */
const statementsQuery = useQuery({
  queryKey: ['reconcile-statements'],
  queryFn: api.reconcileStatements,
})
const statements = computed<ReconcileStatement[]>(() => statementsQuery.data.value ?? [])

const proposals = ref(false)
const building = ref<number | null>(null)
const error = ref('')

// ── Date range ──────────────────────────────────────────────────────────────
// `yyyy-mm-dd`, both inclusive, either may be empty.
const dateFrom = ref('')
const dateTo = ref('')
const ranged = computed(() => Boolean(dateFrom.value || dateTo.value))
const backwards = computed(() => Boolean(dateFrom.value && dateTo.value && dateFrom.value > dateTo.value))
const active = computed(() => ranged.value && !backwards.value)

function clearRange() {
  dateFrom.value = ''
  dateTo.value = ''
}

/** The dates a statement's dossier covers: its own period, cut to the range. */
function span(s: ReconcileStatement): { from: string | null; to: string | null } {
  let from = s.period_from
  let to = s.period_to
  if (active.value) {
    if (dateFrom.value && (!from || dateFrom.value > from)) from = dateFrom.value
    if (dateTo.value && (!to || dateTo.value < to)) to = dateTo.value
  }
  return { from, to }
}

function overlaps(s: ReconcileStatement) {
  if (!s.period_from || !s.period_to) return true // undated: its lines decide
  return (!dateTo.value || s.period_from <= dateTo.value) && (!dateFrom.value || s.period_to >= dateFrom.value)
}

const candidates = computed(() => (active.value ? statements.value.filter(overlaps) : statements.value))

// With a range, the figures come from the lines themselves.
const movementQueries = useQueries({
  queries: computed(() =>
    active.value
      ? candidates.value.map((s) => ({
          queryKey: ['reconcile-movements', s.id],
          queryFn: () => api.reconcileMovements(s.id),
        }))
      : [],
  ),
})

interface Tally {
  lines: number
  payments: number
  confirmed: number
  proposed: number
  open: number
}

const tallies = computed(() => {
  const result = new Map<number, Tally | null>()
  if (!active.value) {
    for (const s of statements.value) {
      result.set(s.id, {
        lines: 1,
        payments: s.payments,
        confirmed: s.confirmed,
        proposed: s.proposed,
        open: s.unmatched + s.proposed,
      })
    }
    return result
  }
  candidates.value.forEach((s, i) => {
    const movements: Movement[] | undefined = movementQueries.value[i]?.data
    if (!movements) {
      result.set(s.id, null)
      return
    }
    const inside = movements.filter(
      (m) => m.data && (!dateFrom.value || m.data >= dateFrom.value) && (!dateTo.value || m.data <= dateTo.value),
    )
    const count = (status: string) => inside.filter((m) => m.match_status === status).length
    result.set(s.id, {
      lines: inside.length,
      payments: inside.filter((m) => m.categoria === 'pagament').length,
      confirmed: count('confirmed'),
      proposed: count('proposed'),
      open: count('unmatched') + count('proposed'),
    })
  })
  return result
})

/** Statements with something in the range; one still counting stays until it knows. */
const visible = computed(() => candidates.value.filter((s) => (tallies.value.get(s.id)?.lines ?? 1) > 0))

function period(s: ReconcileStatement) {
  const { from, to } = span(s)
  if (!from) return '—'
  return from === to ? formatDate(from) : `${formatDate(from)} – ${formatDate(to)}`
}

function share(t: Tally) {
  return t.payments ? Math.round((t.confirmed / t.payments) * 100) : 0
}

/** What the PDF will hold, in words: how many sheets it gets. */
function sheets(t: Tally) {
  const count = t.confirmed + (proposals.value ? t.proposed : 0)
  return count === 1 ? '1 fitxa' : `${count} fitxes`
}

async function generate(statement: ReconcileStatement) {
  building.value = statement.id
  error.value = ''
  try {
    await api.downloadStatementDossier(statement, proposals.value, active.value ? span(statement) : {})
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
          de la factura. Els originals en PDF s'hi afegeixen sencers. Amb unes dates, només hi
          entren els moviments d'aquell període.
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

      <div class="range">
        <span class="range-label">Dates</span>
        <input v-model="dateFrom" class="input input-mono" type="date" aria-label="Des de" :max="dateTo || undefined" />
        <span class="muted">–</span>
        <input v-model="dateTo" class="input input-mono" type="date" aria-label="Fins a" :min="dateFrom || undefined" />
        <button v-if="ranged" class="btn btn-ghost btn-sm" type="button" @click="clearRange">
          <AppIcon name="close" :size="13" />
          Treu
        </button>
        <span v-if="backwards" class="range-note error-text">La data d'inici és posterior a la de final.</span>
        <span v-else-if="active" class="range-note muted">Cada PDF només amb els moviments d'aquestes dates.</span>
        <span v-else class="range-note muted">Sense dates, l'extracte sencer.</span>
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
      <p v-else-if="active && !visible.length" class="empty">
        Cap extracte té moviments en aquestes dates.
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
            <tr v-for="s in visible" :key="s.id">
              <td><strong>{{ s.compte }}</strong></td>
              <td class="mono">{{ period(s) }}</td>
              <td>
                {{ SOURCE_LABEL[s.source] ?? s.source }}
                <span class="sub muted truncate" :title="s.file_name">{{ s.file_name }}</span>
              </td>
              <template v-if="tallies.get(s.id)">
                <td>
                  <div class="progress">
                    <span class="count">{{ tallies.get(s.id)!.confirmed }} / {{ tallies.get(s.id)!.payments }}</span>
                    <span class="bar"><span :style="{ width: `${share(tallies.get(s.id)!)}%` }" /></span>
                  </div>
                </td>
                <td class="num">
                  <span :class="{ muted: !tallies.get(s.id)!.open }">{{ tallies.get(s.id)!.open }}</span>
                </td>
              </template>
              <template v-else>
                <td class="muted">Comptant…</td>
                <td class="num muted">…</td>
              </template>
              <td class="actions">
                <div class="row-actions">
                  <span v-if="tallies.get(s.id)" class="muted sheets">{{ sheets(tallies.get(s.id)!) }}</span>
                  <button
                    class="btn btn-outline btn-sm"
                    type="button"
                    :disabled="building !== null || backwards"
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

.range {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
  padding: 10px 16px;
  border-bottom: 1px solid var(--line);
  font-size: var(--text-sm);
}

.range-label {
  font-weight: 600;
  color: var(--ink-500);
}

.range .input {
  width: 148px;
  padding: 4px 8px;
}

.range-note {
  font-size: var(--text-xs);
}

.error-text {
  color: var(--danger-700);
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
