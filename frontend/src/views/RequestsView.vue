<script setup lang="ts">
/**
 * Sol·licituds. One screen, two readings: the office sees every request as an
 * inbox to work through; a teacher sees their own, and asks for more.
 */
import { computed, ref, watch } from 'vue'
import { useQuery, useQueryClient } from '@tanstack/vue-query'
import { useRoute, useRouter } from 'vue-router'

import { api } from '../api/client'
import type { AiFilterResult, AiTableSpec, RequestDetail, RequestKind, RequestSummary } from '../api/types'
import AiSearchInput from '../components/AiSearchInput.vue'
import AppIcon from '../components/AppIcon.vue'
import FilterChip from '../components/FilterChip.vue'
import NewRequestDialog from '../components/NewRequestDialog.vue'
import RequestStatusPill from '../components/RequestStatusPill.vue'
import RequestWindow from '../components/RequestWindow.vue'
import SortTh from '../components/SortTh.vue'
import { choiceFilter, useAiFilters } from '../composables/useAiFilters'
import { useAuth } from '../composables/useAuth'
import { useTableQuery } from '../composables/useTableQuery'
import { formatAmount, formatDate } from '../document-fields'
import { KIND_ICON, KIND_LABEL, KINDS, OPEN_STATUSES, STATUS_META } from '../requests'

const auth = useAuth()
const route = useRoute()
const router = useRouter()
const queryClient = useQueryClient()

const requestsQuery = useQuery({
  queryKey: ['requests'],
  queryFn: api.listRequests,
  refetchInterval: 30_000,
})
const requests = computed<RequestSummary[]>(() => requestsQuery.data.value ?? [])

const isOffice = computed(() => auth.isStaff.value)
const meId = computed(() => auth.user.value?.id)

/**
 * The cards across the top. For the office: what is waiting (the default),
 * what is theirs, and everything. A teacher's are the same idea, from their side.
 */
type View = '' | 'meves' | 'totes'
function inView(item: RequestSummary, view: string) {
  if (view === 'totes') return true
  if (view === 'meves') {
    return isOffice.value
      ? item.assignee?.id === meId.value && OPEN_STATUSES.includes(item.status)
      : !OPEN_STATUSES.includes(item.status)
  }
  return OPEN_STATUSES.includes(item.status)
}

const counts = computed(() => ({
  waiting: requests.value.filter((r) => inView(r, '')).length,
  mine: requests.value.filter((r) => inView(r, 'meves')).length,
  all: requests.value.length,
  unassigned: requests.value.filter((r) => OPEN_STATUSES.includes(r.status) && !r.assignee).length,
}))

const STATUS_RANK: Record<string, number> = { oberta: 0, en_revisio: 1, aprovada: 2, rebutjada: 3, resolta: 4, cancellada: 5 }

const table = useTableQuery({
  rows: requests,
  sorts: {
    codi: (r) => r.id,
    titol: (r) => r.title,
    qui: (r) => r.requester.name,
    import: (r) => r.amount,
    estat: (r) => STATUS_RANK[r.status],
    activitat: (r) => r.last_activity_at,
  },
  search: (r) => [r.code, r.title, r.requester.name, r.proveidor, r.compte, r.assignee?.name, KIND_LABEL[r.kind]],
  filters: {
    vista: (r, value) => inView(r, value),
    tipus: (r, value) => r.kind === value,
    estat: (r, value) => r.status === value,
  },
})
// `vista` is '' for the default view, so its predicate never runs for it:
// apply that one here.
const visible = computed(() =>
  table.filters.vista ? table.visible.value : table.visible.value.filter((r) => inView(r, '')),
)
const KIND_OPTIONS = KINDS.map((kind) => ({ value: kind, label: KIND_LABEL[kind] }))
const STATUS_OPTIONS = Object.entries(STATUS_META).map(([value, meta]) => ({ value, label: meta.label }))
/** Counts within the current view card, like the list itself. */
function countIn(name: 'tipus' | 'estat', value: string) {
  if (table.filters.vista) return table.countFor(name, value)
  return requests.value.filter(
    (r) => inView(r, '') && (!value || (name === 'tipus' ? r.kind === value : r.status === value)),
  ).length
}

const view = computed<View>({
  get: () => (table.filters.vista || '') as View,
  set: (value) => (table.filters.vista = value),
})

// ── Asking the AI ───────────────────────────────────────────────────────────
const REQUEST_AI: AiTableSpec = {
  subject: "sol·licituds de compra, pagament i consulta a la secretaria",
  search_hint: 'codi, títol, qui la demana, proveïdor, compte, qui la porta',
  filters: [choiceFilter('tipus', 'Tipus', KIND_OPTIONS), choiceFilter('estat', 'Estat', STATUS_OPTIONS)],
}
const REQUEST_AI_EXAMPLES = ['Compres pendents', 'Les rebutjades', 'Sol·licituds de la Marta']
const requestAi = useAiFilters(table, ['tipus', 'estat'])
const askRequests = (question: string) => api.aiSearch(REQUEST_AI, question)

function applyAi(result: AiFilterResult) {
  requestAi.apply(result)
  // A status is only offered, and only shows, across every request.
  if (table.filters.estat) table.filters.vista = 'totes'
}

// ── The window ──────────────────────────────────────────────────────────────
const openId = computed(() => {
  const raw = route.query.sol
  const id = typeof raw === 'string' ? Number(raw) : NaN
  return Number.isFinite(id) ? id : null
})
/** The list as it was when the window opened, so J/K walk a stable order. */
const queue = ref<number[]>([])

function openRequest(id: number) {
  if (openId.value === null) queue.value = visible.value.map((r) => r.id)
  void router.push({ query: { ...route.query, sol: String(id) } })
}
function switchTo(id: number) {
  void router.replace({ query: { ...route.query, sol: String(id) } })
}
function closeWindow() {
  const { sol: _sol, ...rest } = route.query
  void router.replace({ query: rest })
  void queryClient.invalidateQueries({ queryKey: ['requests'] })
}
const windowQueue = computed(() =>
  openId.value !== null && !queue.value.includes(openId.value) ? [openId.value] : queue.value,
)

// ── Asking ──────────────────────────────────────────────────────────────────
const asking = ref<RequestKind | null>(null)
// `?nova=compra` (from a teacher's home) opens the form on that kind.
watch(
  () => route.query.nova,
  (value) => {
    if (typeof value !== 'string' || !KINDS.includes(value as RequestKind)) return
    asking.value = value as RequestKind
    const { nova: _nova, ...rest } = route.query
    void router.replace({ query: rest })
  },
  { immediate: true },
)
function created(request: RequestDetail) {
  asking.value = null
  void queryClient.invalidateQueries({ queryKey: ['requests'] })
  queue.value = [request.id]
  void router.push({ query: { ...route.query, sol: String(request.id) } })
}

function ago(iso: string) {
  const minutes = Math.round((Date.now() - new Date(iso).getTime()) / 60_000)
  if (minutes < 60) return minutes < 1 ? 'ara' : `fa ${minutes} min`
  const hours = Math.round(minutes / 60)
  if (hours < 24) return `fa ${hours} h`
  return formatDate(iso.slice(0, 10))
}
</script>

<template>
  <div class="requests">
    <header class="page-head">
      <div>
        <h1 class="page-title">{{ isOffice ? 'Sol·licituds' : 'Les meves sol·licituds' }}</h1>
        <p class="page-lead">
          <template v-if="isOffice">Compres, pressupostos, reemborsaments i preguntes del professorat.</template>
          <template v-else>Demana a secretaria una compra, un pressupost, un reemborsament o fes-li una pregunta.</template>
        </p>
      </div>
      <button class="btn btn-primary" type="button" @click="asking = 'compra'">
        <AppIcon name="plus" />
        Nova sol·licitud
      </button>
    </header>

    <!-- A teacher with nothing asked yet starts from what they can ask. -->
    <section v-if="!isOffice && requestsQuery.isSuccess.value && !requests.length" class="starters">
      <button v-for="kind in KINDS" :key="kind" class="starter" type="button" @click="asking = kind">
        <AppIcon :name="KIND_ICON[kind]" :size="18" />
        <strong>{{ KIND_LABEL[kind] }}</strong>
      </button>
    </section>

    <template v-else>
      <section class="stats" aria-label="Vistes">
        <button class="stat" :class="{ on: view === '' }" type="button" @click="view = ''">
          <span class="stat-label">{{ isOffice ? 'Per atendre' : 'En curs' }}</span>
          <span class="stat-value" :class="{ attention: isOffice && counts.waiting > 0 }">{{ counts.waiting }}</span>
          <span v-if="isOffice && counts.unassigned" class="stat-note">{{ counts.unassigned }} sense assignar</span>
        </button>
        <button class="stat" :class="{ on: view === 'meves' }" type="button" @click="view = 'meves'">
          <span class="stat-label">{{ isOffice ? 'Assignades a mi' : 'Decidides' }}</span>
          <span class="stat-value">{{ counts.mine }}</span>
        </button>
        <button class="stat" :class="{ on: view === 'totes' }" type="button" @click="view = 'totes'">
          <span class="stat-label">Totes</span>
          <span class="stat-value">{{ counts.all }}</span>
        </button>
      </section>

      <section class="card">
        <div class="card-head list-head">
          <div class="filters">
            <AiSearchInput
              v-model="table.search.value"
              class="search"
              :ask="askRequests"
              placeholder="Cerca per títol, persona, proveïdor…"
              ai-placeholder="«Compres pendents de la Marta»…"
              :examples="REQUEST_AI_EXAMPLES"
              storage-key="requests"
              @apply="applyAi"
              @undo="requestAi.undo"
            />
            <FilterChip
              v-model="table.filters.tipus"
              label="Tipus"
              icon="inbox"
              :options="KIND_OPTIONS"
              :count="(v) => countIn('tipus', v)"
            />
            <FilterChip
              v-if="view === 'totes'"
              v-model="table.filters.estat"
              label="Estat"
              icon="check"
              :options="STATUS_OPTIONS"
              :count="(v) => countIn('estat', v)"
            />
          </div>
          <span class="count muted">{{ visible.length }}</span>
        </div>

        <p v-if="requestsQuery.isLoading.value" class="empty">Carregant…</p>
        <p v-else-if="!visible.length" class="empty">
          {{ view === '' && isOffice ? 'No hi ha res pendent.' : 'Cap sol·licitud coincideix amb aquest filtre.' }}
        </p>
        <div v-else class="table-scroll">
          <table class="table">
            <thead>
              <tr>
                <SortTh :table="table" sort-key="titol">Sol·licitud</SortTh>
                <SortTh v-if="isOffice" :table="table" sort-key="qui">Qui</SortTh>
                <SortTh :table="table" sort-key="import" class="num">Import</SortTh>
                <SortTh :table="table" sort-key="estat">Estat</SortTh>
                <th v-if="isOffice">Se n'encarrega</th>
                <SortTh :table="table" sort-key="activitat">Últim moviment</SortTh>
              </tr>
            </thead>
            <tbody>
              <tr
                v-for="item in visible"
                :key="item.id"
                class="row"
                :class="{ current: item.id === openId }"
                tabindex="0"
                @click="openRequest(item.id)"
                @keydown.enter="openRequest(item.id)"
              >
                <td>
                  <div class="what">
                    <span class="kind-icon" :title="KIND_LABEL[item.kind]">
                      <AppIcon :name="KIND_ICON[item.kind]" :size="14" />
                    </span>
                    <span class="what-text">
                      <strong class="truncate">{{ item.title }}</strong>
                      <span class="sub muted">
                        <span class="mono">{{ item.code }}</span> · {{ KIND_LABEL[item.kind] }}
                        <template v-if="item.message_count">
                          · <AppIcon name="message" :size="11" /> {{ item.message_count }}
                        </template>
                        <template v-if="item.document_count">
                          · <AppIcon name="invoice" :size="11" /> {{ item.document_count }}
                        </template>
                      </span>
                    </span>
                  </div>
                </td>
                <td v-if="isOffice" class="who">{{ item.requester.name }}</td>
                <td class="num">{{ item.amount != null ? formatAmount(item.amount) : '' }}</td>
                <td><RequestStatusPill :status="item.status" /></td>
                <td v-if="isOffice" :class="{ muted: !item.assignee }">{{ item.assignee?.name ?? '—' }}</td>
                <td class="muted when">{{ ago(item.last_activity_at) }}</td>
              </tr>
            </tbody>
          </table>
        </div>
      </section>
    </template>

    <RequestWindow
      v-if="openId !== null"
      :id="openId"
      :queue="windowQueue"
      @open="switchTo"
      @close="closeWindow"
    />
    <NewRequestDialog v-if="asking" :initial-kind="asking" @close="asking = null" @created="created" />
  </div>
</template>

<style scoped>
.requests {
  display: grid;
  grid-template-columns: minmax(0, 1fr);
  gap: 16px;
}

.page-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
}

.starters {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(160px, 1fr));
  gap: 10px;
}

.starter {
  display: grid;
  justify-items: start;
  gap: 8px;
  padding: 16px;
  border: 1px solid var(--line);
  border-radius: var(--r-lg);
  background: var(--surface-0);
  color: var(--accent-700);
  font: inherit;
  text-align: left;
  cursor: pointer;
}

.starter strong {
  color: var(--ink-900);
}

.starter:hover {
  border-color: var(--accent-300);
  box-shadow: var(--shadow-sm);
}

.stats {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 180px));
  gap: 8px;
}

.stat {
  display: grid;
  gap: 2px;
  padding: 10px 12px;
  border: 1px solid var(--line);
  border-radius: var(--r-lg);
  background: var(--surface-0);
  font: inherit;
  text-align: left;
  cursor: pointer;
}

.stat:hover {
  border-color: var(--line-strong);
}

.stat.on {
  border-color: var(--accent-400);
  box-shadow: 0 0 0 1px var(--accent-400);
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
  color: var(--ink-900);
}

.stat-value.attention {
  color: var(--accent-700);
}

.stat-note {
  font-size: var(--text-xs);
  color: var(--gold-800);
}

.list-head {
  align-items: center;
}

.filters {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  flex: 1;
  min-width: 0;
}

.search {
  flex: 1 1 220px;
  max-width: 360px;
}

.count {
  font-size: var(--text-sm);
  font-variant-numeric: tabular-nums;
}

.row {
  cursor: pointer;
}

.row:focus-visible {
  outline: 2px solid var(--accent-500);
  outline-offset: -2px;
}

.row.current td {
  background: var(--accent-50);
}

.what {
  display: flex;
  align-items: flex-start;
  gap: 9px;
  min-width: 0;
  max-width: 460px;
}

.kind-icon {
  display: grid;
  place-items: center;
  flex: none;
  width: 26px;
  height: 26px;
  border-radius: var(--r-md);
  background: var(--accent-50);
  color: var(--accent-700);
}

.what-text {
  display: grid;
  min-width: 0;
  line-height: 1.35;
}

.sub {
  display: inline-flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 3px;
  font-size: var(--text-sm);
}

.who,
.when {
  white-space: nowrap;
}

@media (max-width: 640px) {
  .page-head {
    flex-direction: column;
  }

  .stats {
    grid-template-columns: repeat(3, minmax(0, 1fr));
  }
}
</style>
