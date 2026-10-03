<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { useMutation, useQuery, useQueryClient } from '@tanstack/vue-query'
import { RouterLink, useRoute, useRouter } from 'vue-router'

import { api } from '../api/client'
import type { DocumentBrief, MatchRun, Movement, MovementDetail, PaymentMatch, ReconcileStatement } from '../api/types'
import { formatAmount, formatDate } from '../document-fields'
import {
  BAND_LABEL,
  CATEGORIA_LABEL,
  DECIDED_LABEL,
  SIGNAL_LABEL,
  SOURCE_LABEL,
  STATUS_LABEL,
  band,
} from '../matching'
import AppIcon from '../components/AppIcon.vue'
import DocumentPeek from '../components/DocumentPeek.vue'
import MovementCard from '../components/MovementCard.vue'

/**
 * Justifying a statement: the AI proposes an invoice for each movement, a
 * person confirms. Nothing runs until "Començar justificació" is pressed, and
 * nothing reaches the register until a proposal is confirmed.
 */
const route = useRoute()
const router = useRouter()
const queryClient = useQueryClient()

// ── Which statement ──────────────────────────────────────────────────────────

const statementsQuery = useQuery({ queryKey: ['reconcile-statements'], queryFn: api.reconcileStatements })
const statements = computed<ReconcileStatement[]>(() => statementsQuery.data.value ?? [])

/** The five places money moves, in the order people think of them. */
const ACCOUNTS = ['General', 'Material i Sortides', 'Menjador', 'Targeta Prepagament', 'Caixeta']

/** Prefilter by account; empty means every statement. Kept in the URL. */
const account = computed(() => (typeof route.query.compte === 'string' ? route.query.compte : ''))

const accountChips = computed(() =>
  ACCOUNTS.map((name) => {
    const own = statements.value.filter((s) => s.compte === name)
    return { name, count: own.length, pending: own.reduce((n, s) => n + s.unmatched + s.proposed, 0) }
  }),
)

/**
 * Newest first: the latest period, then the latest brought in. A statement
 * whose every line was already known (dropped twice, or covered by a longer
 * one) has nothing of its own to justify, so it goes to the end, greyed.
 */
const shown = computed(() =>
  statements.value
    .filter((s) => !account.value || s.compte === account.value)
    .slice()
    .sort(
      (a, b) =>
        Number(!a.payments) - Number(!b.payments) ||
        (b.period_to ?? '').localeCompare(a.period_to ?? '') ||
        b.created_at.localeCompare(a.created_at),
    ),
)

const statementId = computed<number | null>(() => {
  const asked = Number(route.query.extracte)
  if (asked && shown.value.some((s) => s.id === asked)) return asked
  return (shown.value.find((s) => s.payments) ?? shown.value[0])?.id ?? null
})
const statement = computed(() => statements.value.find((s) => s.id === statementId.value) ?? null)

function pickStatement(id: number) {
  void router.replace({ query: { ...route.query, extracte: String(id) } })
  selectedId.value = null
}

function pickAccount(name: string) {
  const query = { ...route.query }
  delete query.extracte
  if (name && name !== account.value) query.compte = name
  else delete query.compte
  void router.replace({ query })
  selectedId.value = null
}

function shortPeriod(s: ReconcileStatement) {
  if (!s.period_from || !s.period_to) return 'Sense moviments'
  const sameYear = s.period_from.slice(0, 4) === s.period_to.slice(0, 4)
  const from = formatDate(s.period_from)
  return `${sameYear ? from.slice(0, 5) : from} – ${formatDate(s.period_to)}`
}

function share(s: ReconcileStatement) {
  return s.payments ? Math.round((s.confirmed / s.payments) * 100) : 0
}

// The strip scrolls sideways; let an ordinary mouse wheel do it too.
const strip = ref<HTMLElement | null>(null)
function onWheel(event: WheelEvent) {
  const el = strip.value
  if (!el || Math.abs(event.deltaX) > Math.abs(event.deltaY)) return
  if (el.scrollWidth <= el.clientWidth) return
  el.scrollLeft += event.deltaY
  event.preventDefault()
}
function scrollStrip(direction: 1 | -1) {
  strip.value?.scrollBy({ left: direction * 480, behavior: 'smooth' })
}
watch(statementId, async (id) => {
  await nextTick()
  strip.value?.querySelector<HTMLElement>(`[data-statement="${id}"]`)?.scrollIntoView({
    block: 'nearest',
    inline: 'nearest',
    behavior: 'smooth',
  })
})

// ── The run ──────────────────────────────────────────────────────────────────

const run = ref<MatchRun | null>(null)
const runError = ref('')
const running = computed(() => run.value?.status === 'running')

const activeRunQuery = useQuery({
  queryKey: computed(() => ['match-run', statementId.value]),
  queryFn: () => api.activeMatchRun(statementId.value as number),
  enabled: computed(() => statementId.value !== null),
})
watch(
  () => activeRunQuery.data.value,
  (found) => {
    if (found) run.value = found
  },
)

let timer: number | undefined
async function poll() {
  if (!run.value || run.value.status !== 'running') return
  try {
    run.value = await api.matchRun(run.value.id)
  } catch {
    /* keep polling; a blip is not a failure */
  }
  void queryClient.invalidateQueries({ queryKey: ['reconcile-movements'] })
  void queryClient.invalidateQueries({ queryKey: ['reconcile-movement'] })
  if (run.value?.status === 'running') {
    timer = window.setTimeout(poll, 1500)
  } else {
    refreshAll()
  }
}
watch(running, (now) => {
  if (now) {
    window.clearTimeout(timer)
    timer = window.setTimeout(poll, 1200)
  }
})
onBeforeUnmount(() => window.clearTimeout(timer))

const startRun = useMutation({
  mutationFn: () => api.startMatchRun(statementId.value),
  onMutate: () => {
    runError.value = ''
  },
  onSuccess: (started) => {
    run.value = started
    if (started.status !== 'running') refreshAll()
  },
  onError: (error) => {
    runError.value = error instanceof Error ? error.message : String(error)
  },
})

// ── Movements ────────────────────────────────────────────────────────────────

type Filter = 'pending' | 'all' | 'confirmed'
const filter = ref<Filter>('pending')
const showOthers = ref(false)

const movementsQuery = useQuery({
  queryKey: computed(() => ['reconcile-movements', statementId.value]),
  queryFn: () => api.reconcileMovements(statementId.value as number),
  enabled: computed(() => statementId.value !== null),
})
const movements = computed<Movement[]>(() => movementsQuery.data.value ?? [])
const payments = computed(() => movements.value.filter((m) => m.categoria === 'pagament'))
const others = computed(() => movements.value.filter((m) => m.categoria !== 'pagament'))

const PENDING = new Set(['unmatched', 'proposed', 'no_match'])
const visible = computed(() =>
  payments.value
    .filter((m) =>
      filter.value === 'all' ? true : filter.value === 'confirmed' ? m.match_status === 'confirmed' : PENDING.has(m.match_status),
    )
    // Proposals first, surest first: the quick confirmations come before the thinking.
    .sort((a, b) => order(a) - order(b) || (b.confidence ?? -1) - (a.confidence ?? -1)),
)

function order(m: Movement) {
  return { proposed: 0, no_match: 1, unmatched: 2, confirmed: 3, rejected: 4, not_applicable: 5 }[m.match_status]
}

const counts = computed(() => {
  const list = payments.value
  return {
    pending: list.filter((m) => PENDING.has(m.match_status)).length,
    all: list.length,
    confirmed: list.filter((m) => m.match_status === 'confirmed').length,
    unmatched: list.filter((m) => m.match_status === 'unmatched').length,
  }
})

const bands = computed(() => {
  const proposed = payments.value.filter((m) => m.match_status === 'proposed')
  return {
    high: proposed.filter((m) => band(m.confidence) === 'high').length,
    medium: proposed.filter((m) => band(m.confidence) === 'medium').length,
    low: proposed.filter((m) => band(m.confidence) === 'low').length,
    none: payments.value.filter((m) => m.match_status === 'unmatched' || m.match_status === 'no_match').length,
  }
})

const progress = computed(() => (counts.value.all ? Math.round((counts.value.confirmed / counts.value.all) * 100) : 0))

// ── Selection ────────────────────────────────────────────────────────────────

const selectedId = ref<number | null>(null)
watch(visible, (list) => {
  if (!list.length) {
    selectedId.value = null
  } else if (!list.some((m) => m.id === selectedId.value) && !others.value.some((m) => m.id === selectedId.value)) {
    selectedId.value = list[0].id
  }
})

const detailQuery = useQuery({
  queryKey: computed(() => ['reconcile-movement', selectedId.value]),
  queryFn: () => api.reconcileMovement(selectedId.value as number),
  enabled: computed(() => selectedId.value !== null),
})
const detail = computed<MovementDetail | null>(() => detailQuery.data.value ?? null)

type Group = { key: number; status: string; confidence: number; matches: PaymentMatch[] }
function groups(status: PaymentMatch['status'][]): Group[] {
  const map = new Map<number, Group>()
  for (const match of detail.value?.matches ?? []) {
    if (!status.includes(match.status)) continue
    const entry = map.get(match.group) ?? { key: match.group, status: match.status, confidence: match.confidence, matches: [] }
    entry.matches.push(match)
    map.set(match.group, entry)
  }
  return [...map.values()]
}
const confirmed = computed(() => groups(['confirmed'])[0] ?? null)
const lead = computed(() => groups(['proposed'])[0] ?? null)
const candidates = computed(() => [...groups(['proposed']).slice(0, 1), ...groups(['alternative']).slice(0, 3)])

// The candidate open in the comparison panel: the proposal, unless one of the
// others has been clicked to look at it side by side with the movement.
const focusKey = ref<number | null>(null)
const viewed = computed(() => candidates.value.find((g) => g.key === focusKey.value) ?? lead.value)
const viewedMatch = computed(() => viewed.value?.matches[0] ?? null)
const alternatives = computed(() => candidates.value.filter((g) => g !== viewed.value))

function step(offset: number) {
  const list = visible.value
  const index = list.findIndex((m) => m.id === selectedId.value)
  const next = list[Math.min(list.length - 1, Math.max(0, index + offset))]
  if (next) selectedId.value = next.id
}

function refreshAll() {
  void queryClient.invalidateQueries({ queryKey: ['reconcile-statements'] })
  void queryClient.invalidateQueries({ queryKey: ['reconcile-movements'] })
  void queryClient.invalidateQueries({ queryKey: ['reconcile-movement'] })
  void queryClient.invalidateQueries({ queryKey: ['documents'] })
}

// ── Decisions ────────────────────────────────────────────────────────────────

const actionError = ref('')

function after(updated: MovementDetail, advance: boolean) {
  queryClient.setQueryData(['reconcile-movement', updated.id], updated)
  const index = visible.value.findIndex((m) => m.id === updated.id)
  refreshAll()
  if (advance) {
    // Move on to the next pending one, the way a person works down a statement.
    const next = visible.value.slice(index + 1).find((m) => PENDING.has(m.match_status))
    if (next) selectedId.value = next.id
  }
}

const decide = useMutation({
  mutationFn: async (action: { kind: 'confirm'; refs: string[] } | { kind: 'reject' } | { kind: 'not-this'; matchId: number } | { kind: 'undo' } | { kind: 'repropose' }) => {
    const id = selectedId.value as number
    if (action.kind === 'confirm') return { updated: await api.confirmMatch(id, action.refs), advance: true }
    if (action.kind === 'reject') return { updated: await api.rejectMovement(id), advance: true }
    if (action.kind === 'not-this') return { updated: await api.rejectMatch(action.matchId), advance: false }
    if (action.kind === 'undo') return { updated: await api.undoMovement(id), advance: false }
    return { updated: await api.reproposeMovement(id), advance: false }
  },
  onMutate: () => {
    actionError.value = ''
  },
  onSuccess: ({ updated, advance }) => after(updated, advance),
  onError: (error) => {
    actionError.value = error instanceof Error ? error.message : String(error)
  },
})

function confirmGroup(group: Group) {
  decide.mutate({ kind: 'confirm', refs: group.matches.map((m) => m.document.num_doc_intern) })
}

// ── Manual search ────────────────────────────────────────────────────────────

const search = ref('')
const searchResults = ref<DocumentBrief[]>([])
let searchTimer: number | undefined
watch(search, (text) => {
  window.clearTimeout(searchTimer)
  if (text.trim().length < 2) {
    searchResults.value = []
    return
  }
  searchTimer = window.setTimeout(async () => {
    searchResults.value = await api.searchInvoices(text.trim())
  }, 250)
})
watch(selectedId, () => {
  search.value = ''
  actionError.value = ''
  focusKey.value = null
})

// ── Keyboard ─────────────────────────────────────────────────────────────────

function onKey(event: KeyboardEvent) {
  const target = event.target as HTMLElement | null
  if (target && ['INPUT', 'SELECT', 'TEXTAREA'].includes(target.tagName)) return
  if (event.key === 'Escape' && peekOpen.value) {
    peekOpen.value = false
    return
  }
  if ((event.key === 'p' || event.key === 'P') && hoverCard.value) {
    pin(hoverCard.value)
    return
  }
  if (event.key === 'o' && peekDoc.value) {
    showOriginal(peekDoc.value)
    return
  }
  if (event.key === 'ArrowDown' || event.key === 'j') {
    step(1)
    event.preventDefault()
  } else if (event.key === 'ArrowUp' || event.key === 'k') {
    step(-1)
    event.preventDefault()
  } else if (event.key === 'Enter' && viewed.value && !confirmed.value && !decide.isPending.value) {
    confirmGroup(viewed.value)
    event.preventDefault()
  } else if ((event.key === 'r' || event.key === 'R') && detail.value && detail.value.match_status !== 'confirmed') {
    decide.mutate({ kind: 'reject' })
  }
}
onMounted(() => window.addEventListener('keydown', onKey))
onBeforeUnmount(() => window.removeEventListener('keydown', onKey))

// ── Presentation ─────────────────────────────────────────────────────────────

function signalTone(value: number | undefined) {
  if (!value) return 'off'
  return value >= 0.99 ? 'on' : 'part'
}

function signalText(key: string, match: PaymentMatch) {
  if (key === 'date' && match.document.data_factura && detail.value?.data) {
    const days = Math.round(
      (new Date(detail.value.data).getTime() - new Date(match.document.data_factura).getTime()) / 86400000,
    )
    return `Data ${days >= 0 ? '+' : ''}${days} d`
  }
  return SIGNAL_LABEL[key] ?? key
}

const SIGNALS = ['amount', 'number', 'cif', 'iban', 'name', 'date']

function pct(value: number | undefined) {
  return value == null ? '—' : `${Math.round(value * 100)} %`
}

/** The statement mixes payment methods (a bank account), so each line says which. */
const mixedTipus = computed(() => new Set(payments.value.map((m) => m.tipus).filter(Boolean)).size > 1)

function subline(m: Movement) {
  return [m.mes_dades, mixedTipus.value || !m.mes_dades ? m.tipus : ''].filter(Boolean).join(' · ')
}

// ── Originals ────────────────────────────────────────────────────────────────

/** Fetched once per invoice and kept for the visit: stepping back is instant. */
type Original = { url: string; type: string } | 'loading' | 'missing'
const originals = reactive(new Map<string, Original>())

async function loadOriginal(doc: DocumentBrief) {
  if (!doc.file_url || originals.has(doc.num_doc_intern)) return
  originals.set(doc.num_doc_intern, 'loading')
  try {
    originals.set(doc.num_doc_intern, await api.getDocumentFile(doc.num_doc_intern))
  } catch {
    originals.set(doc.num_doc_intern, 'missing')
  }
}
onBeforeUnmount(() => {
  for (const entry of originals.values()) if (typeof entry === 'object') URL.revokeObjectURL(entry.url)
})

/** The invoices the card is showing: the confirmed ones, else the proposal. */
const shownDocs = computed(() => (confirmed.value ?? lead.value)?.matches.map((m) => m.document) ?? [])
watch(shownDocs, (docs) => docs.forEach(loadOriginal), { immediate: true })

function thumb(doc: DocumentBrief) {
  const entry = originals.get(doc.num_doc_intern)
  return typeof entry === 'object' && entry.type.startsWith('image/') ? entry.url : null
}

function thumbLabel(doc: DocumentBrief) {
  const entry = originals.get(doc.num_doc_intern)
  if (entry === 'loading' || !entry) return '…'
  if (entry === 'missing') return '—'
  return entry.type === 'application/pdf' ? 'PDF' : 'Fitxer'
}

// ── Detail cards: hover a line for all it carries, pin to keep it ──────────────

type Card = { movement: Movement; x: number; y: number }
const CARD_W = 300
const hoverCard = ref<Card | null>(null)
const pinned = ref<Card[]>([])
let hoverTimer: number | undefined
let leaveTimer: number | undefined

/** Beside the line, kept on screen and clear of the docked original. */
function cardAt(rect: DOMRect): { x: number; y: number } {
  const right = window.innerWidth - 8
  const x = rect.right + 8 + CARD_W <= right ? rect.right + 8 : Math.max(8, rect.right - CARD_W - 120)
  return { x, y: Math.min(Math.max(8, rect.top - 4), window.innerHeight - 320) }
}

function rowEnter(m: Movement, event: MouseEvent) {
  window.clearTimeout(leaveTimer)
  window.clearTimeout(hoverTimer)
  const rect = (event.currentTarget as HTMLElement).getBoundingClientRect()
  // Slow to appear, quick to follow once one is showing.
  hoverTimer = window.setTimeout(
    () => {
      hoverCard.value = pinned.value.some((c) => c.movement.id === m.id) ? null : { movement: m, ...cardAt(rect) }
    },
    hoverCard.value ? 60 : 450,
  )
}

function rowLeave() {
  window.clearTimeout(hoverTimer)
  leaveTimer = window.setTimeout(() => (hoverCard.value = null), 200)
}

function cardEnter() {
  window.clearTimeout(leaveTimer)
}

function pin(card: Card) {
  if (!pinned.value.some((c) => c.movement.id === card.movement.id)) pinned.value.push({ ...card })
  hoverCard.value = null
}

function unpin(card: Card) {
  pinned.value = pinned.value.filter((c) => c !== card)
}

/** The selected line's card, from the button on the right-hand card. */
function pinSelected(event: MouseEvent) {
  if (!detail.value) return
  const existing = pinned.value.find((c) => c.movement.id === detail.value?.id)
  if (existing) return unpin(existing)
  const rect = (event.currentTarget as HTMLElement).getBoundingClientRect()
  pin({ movement: detail.value, x: Math.max(8, rect.left - CARD_W - 8), y: Math.max(8, rect.top) })
}

// A pinned card keeps showing the line's latest state after a decision.
watch(movements, (list) => {
  for (const card of pinned.value) card.movement = list.find((m) => m.id === card.movement.id) ?? card.movement
})

// The docked viewer follows the selection: it shows the picked invoice while it
// is on the card, and the card's first one otherwise.
const peekOpen = ref(false)
const peekRef = ref<string | null>(null)
const peekDoc = computed(
  () => shownDocs.value.find((d) => d.num_doc_intern === peekRef.value) ?? shownDocs.value.find((d) => d.file_url) ?? null,
)
const peekFile = computed(() => {
  const entry = peekDoc.value ? originals.get(peekDoc.value.num_doc_intern) : undefined
  return typeof entry === 'object' ? entry : null
})

/**
 * Where the original first floats: in the free margin right of the page when
 * the screen has one, else over the movement list — the proposal it is being
 * checked against stays in view either way.
 */
function peekHome() {
  const page = document.querySelector('.reconcile')?.getBoundingClientRect()
  const list = document.querySelector('.panes .list')?.getBoundingClientRect()
  const free = page ? window.innerWidth - page.right - 32 : 0
  if (page && free >= 340) return { x: page.right + 16, y: 16, w: Math.min(free, 640), h: window.innerHeight - 32 }
  const top = Math.max(16, list?.top ?? 16)
  return { x: list?.left ?? 16, y: top, w: Math.max(340, (list?.width ?? 440) - 16), h: Math.min(window.innerHeight - top - 16, 760) }
}

function showOriginal(doc: DocumentBrief) {
  if (peekOpen.value && peekDoc.value?.num_doc_intern === doc.num_doc_intern) {
    peekOpen.value = false
    return
  }
  peekRef.value = doc.num_doc_intern
  peekOpen.value = true
}
</script>

<template>
  <div class="reconcile">
    <header class="page-head">
      <div>
        <h1 class="page-title">Justificar extractes</h1>
        <p class="page-lead">
          La IA proposa la factura del registre que correspon a cada moviment; tu la confirmes. Confirmar
          marca la factura com a pagada, amb la data, el mètode i el compte del moviment.
        </p>
      </div>
    </header>

    <p v-if="statementsQuery.isLoading.value" class="empty">Carregant extractes…</p>
    <section v-else-if="!statements.length" class="card empty-card">
      <p class="empty">
        Encara no hi ha cap extracte. Puja'n un a
        <RouterLink :to="{ name: 'statements' }">Bases de dades → Extractes</RouterLink>.
      </p>
    </section>

    <template v-else-if="statement">
      <section class="card toolbar">
        <div class="type-row">
          <span class="picker-label">Extractes</span>
          <div class="type-chips" role="group" aria-label="Filtra per compte">
            <button class="chip" :class="{ on: !account }" type="button" @click="pickAccount('')">
              Tots <span>{{ statements.length }}</span>
            </button>
            <button
              v-for="chip in accountChips"
              :key="chip.name"
              class="chip"
              :class="{ on: account === chip.name }"
              type="button"
              :disabled="!chip.count"
              @click="pickAccount(chip.name)"
            >
              {{ chip.name }}
              <span>{{ chip.count }}</span>
              <i v-if="chip.pending" class="pending-dot" :title="`${chip.pending} pendents`" />
            </button>
          </div>
          <div class="strip-nav">
            <button class="btn btn-ghost btn-icon btn-sm" type="button" title="Més recents" @click="scrollStrip(-1)">
              <AppIcon name="chevron" :size="13" class="flip" />
            </button>
            <button class="btn btn-ghost btn-icon btn-sm" type="button" title="Més antics" @click="scrollStrip(1)">
              <AppIcon name="chevron" :size="13" />
            </button>
          </div>
        </div>

        <div ref="strip" class="strip" role="listbox" aria-label="Extractes, del més recent al més antic" @wheel="onWheel">
          <button
            v-for="s in shown"
            :key="s.id"
            :data-statement="s.id"
            class="st"
            :class="{ on: s.id === statementId, empty: !s.payments }"
            type="button"
            role="option"
            :aria-selected="s.id === statementId"
            @click="pickStatement(s.id)"
          >
            <span class="st-top">
              <strong class="truncate">{{ s.compte }}</strong>
              <span class="st-source">{{ SOURCE_LABEL[s.source] }}</span>
            </span>
            <span class="st-period mono">{{ shortPeriod(s) }}</span>
            <span class="st-bar"><span :style="{ width: `${share(s)}%` }" /></span>
            <span v-if="!s.payments" class="st-foot">
              <span>{{ s.rows_total ? 'Ja inclòs en un altre extracte' : 'Sense moviments' }}</span>
            </span>
            <span v-else class="st-foot">
              <span>{{ s.confirmed }}/{{ s.payments }} justificats</span>
              <span v-if="s.payments && !(s.unmatched + s.proposed)" class="st-ok"><AppIcon name="check" :size="11" /></span>
              <span v-else class="st-dots">
                <template v-if="s.bands.high"><i class="dot high" />{{ s.bands.high }}</template>
                <template v-if="s.bands.medium"><i class="dot medium" />{{ s.bands.medium }}</template>
                <template v-if="s.bands.low"><i class="dot low" />{{ s.bands.low }}</template>
                <template v-if="s.unmatched"><i class="dot none" />{{ s.unmatched }}</template>
              </span>
            </span>
          </button>
        </div>

        <div class="toolbar-main">

          <div class="progress-block">
            <div class="progress-line">
              <span><strong>{{ counts.confirmed }}</strong> de {{ counts.all }} pagaments justificats</span>
              <span class="bands" aria-label="Propostes per confiança">
                <span class="band-count" title="Molt probable"><i class="dot high" />{{ bands.high }}</span>
                <span class="band-count" title="Probable, revisa"><i class="dot medium" />{{ bands.medium }}</span>
                <span class="band-count" title="Dubtosa"><i class="dot low" />{{ bands.low }}</span>
                <span class="band-count" title="Sense proposta"><i class="dot none" />{{ bands.none }}</span>
              </span>
            </div>
            <div class="bar"><span :style="{ width: `${progress}%` }" /></div>
          </div>

          <button
            v-if="!running"
            class="btn btn-primary start"
            type="button"
            :disabled="!counts.unmatched || startRun.isPending.value"
            @click="startRun.mutate()"
          >
            <AppIcon name="sparkle" />
            Començar justificació
            <span class="start-count">{{ counts.unmatched }}</span>
          </button>
          <div v-else class="run-progress" role="status">
            <AppIcon name="refresh" :size="14" class="spin" />
            <span>Proposant… {{ run?.processed }}/{{ run?.total }}</span>
            <div class="bar small">
              <span :style="{ width: `${run && run.total ? (run.processed / run.total) * 100 : 0}%` }" />
            </div>
          </div>
        </div>
        <p v-if="runError" class="notice notice-error"><AppIcon name="alert" :size="15" /> {{ runError }}</p>
        <p v-else-if="run?.status === 'done' && run.total" class="run-done muted">
          Darrera execució: {{ run.proposed }} propostes per a {{ run.total }} moviments.
        </p>
      </section>

      <section class="panes">
        <!-- ── Left: the statement's movements ─────────────────────────── -->
        <div class="card list">
          <div class="chips">
            <button class="chip" :class="{ on: filter === 'pending' }" type="button" @click="filter = 'pending'">
              Pendents <span>{{ counts.pending }}</span>
            </button>
            <button class="chip" :class="{ on: filter === 'all' }" type="button" @click="filter = 'all'">
              Tots <span>{{ counts.all }}</span>
            </button>
            <button class="chip" :class="{ on: filter === 'confirmed' }" type="button" @click="filter = 'confirmed'">
              Confirmats <span>{{ counts.confirmed }}</span>
            </button>
          </div>

          <p v-if="movementsQuery.isLoading.value" class="empty">Carregant…</p>
          <p v-else-if="!visible.length" class="empty">
            {{ filter === 'pending' ? 'No queda res per justificar en aquest extracte.' : 'Cap moviment.' }}
          </p>
          <ul v-else class="movements" role="listbox" aria-label="Moviments">
            <li
              v-for="m in visible"
              :key="m.id"
              class="movement"
              :class="[`band-${m.match_status === 'proposed' ? band(m.confidence) : 'none'}`, { selected: m.id === selectedId }]"
              role="option"
              :aria-selected="m.id === selectedId"
              @click="selectedId = m.id"
              @mouseenter="rowEnter(m, $event)"
              @mouseleave="rowLeave"
            >
              <span class="m-date">
                <span class="mono">{{ formatDate(m.data) }}</span>
                <span v-if="m.external_ref" class="m-ref mono muted">{{ m.external_ref }}</span>
              </span>
              <span class="m-text">
                <span class="truncate">{{ m.concepte }}</span>
                <span class="truncate muted">{{ subline(m) }}</span>
              </span>
              <span class="m-amount">
                <span class="num">{{ formatAmount(m.import_value) }}</span>
                <span v-if="m.saldo != null" class="m-saldo num muted" title="Saldo després del moviment">{{ formatAmount(m.saldo) }}</span>
              </span>
              <span class="m-state">
                <span v-if="m.match_status === 'confirmed'" class="state-confirmed">
                  <AppIcon name="check" :size="11" /> Confirmat
                </span>
                <span v-else-if="m.match_status === 'proposed'" class="pill" :class="band(m.confidence)">
                  <i class="dot" :class="band(m.confidence)" />{{ m.confidence }}
                </span>
                <span v-else class="state-plain">{{ STATUS_LABEL[m.match_status] }}</span>
              </span>
            </li>
          </ul>

          <div v-if="others.length" class="others">
            <button class="btn btn-ghost btn-sm" type="button" @click="showOthers = !showOthers">
              <AppIcon name="chevron" :size="12" :class="{ rotated: showOthers }" />
              {{ others.length }} moviments que no són pagaments
            </button>
            <ul v-if="showOthers" class="movements dim">
              <li
                v-for="m in others"
                :key="m.id"
                class="movement band-none"
                :class="{ selected: m.id === selectedId }"
                @click="selectedId = m.id"
                @mouseenter="rowEnter(m, $event)"
                @mouseleave="rowLeave"
              >
                <span class="m-date mono">{{ formatDate(m.data) }}</span>
                <span class="m-text"><span class="truncate">{{ m.concepte }}</span></span>
                <span class="m-amount num">{{ formatAmount(m.import_value) }}</span>
                <span class="m-state state-plain">{{ CATEGORIA_LABEL[m.categoria] }}</span>
              </li>
            </ul>
          </div>
          <p class="keys muted">↑ ↓ per moure't · Enter confirma · R: cap factura</p>
        </div>

        <!-- ── Right: the selected movement ────────────────────────────── -->
        <div class="card side">
          <p v-if="!selectedId" class="empty">Tria un moviment.</p>
          <p v-else-if="!detail" class="empty">Carregant…</p>
          <template v-else>
            <div class="mv">
              <div class="mv-top">
                <span class="mv-amount" :class="{ in: detail.import_value > 0 }">{{ formatAmount(detail.import_value) }}</span>
                <span class="mv-date mono">
                  {{ formatDate(detail.data) }}
                  <button
                    class="btn btn-ghost btn-icon btn-sm"
                    :class="{ on: pinned.some((c) => c.movement.id === detail?.id) }"
                    type="button"
                    title="Tots els detalls del moviment"
                    @click="pinSelected"
                  >
                    <AppIcon name="info" :size="14" />
                  </button>
                </span>
              </div>
              <div class="mv-concept">{{ detail.concepte }}</div>
              <div v-if="detail.mes_dades" class="mv-extra muted">{{ detail.mes_dades }}</div>
              <div class="mv-meta">
                <span class="badge badge-neutral">{{ detail.compte }}</span>
                <span v-if="detail.tipus" class="badge badge-neutral">{{ detail.tipus }}</span>
                <span class="muted">{{ SOURCE_LABEL[detail.source] }}</span>
                <span v-if="detail.num_factura_hint" class="muted">· núm. {{ detail.num_factura_hint }}</span>
                <span v-if="detail.cif_hint" class="muted">· CIF {{ detail.cif_hint }}</span>
              </div>
              <div v-if="detail.external_ref || detail.saldo != null || (detail.data_valor && detail.data_valor !== detail.data)" class="mv-facts">
                <span v-if="detail.external_ref"><span class="muted">Ref.</span> <span class="mono">{{ detail.external_ref }}</span></span>
                <span v-if="detail.data_valor && detail.data_valor !== detail.data">
                  <span class="muted">Data valor</span> <span class="mono">{{ formatDate(detail.data_valor) }}</span>
                </span>
                <span v-if="detail.saldo != null"><span class="muted">Saldo</span> <span class="num">{{ formatAmount(detail.saldo) }}</span></span>
              </div>
            </div>

            <p v-if="detail.categoria !== 'pagament'" class="notice">
              {{ CATEGORIA_LABEL[detail.categoria] }}: no cal justificar-lo amb una factura.
              <template v-if="detail.linked_movement">
                És l'altra cara de «{{ detail.linked_movement.concepte }}» ({{ detail.linked_movement.compte }},
                {{ formatDate(detail.linked_movement.data) }}).
              </template>
            </p>

            <p v-if="actionError" class="notice notice-error"><AppIcon name="alert" :size="15" /> {{ actionError }}</p>

            <!-- Confirmed -->
            <section v-if="confirmed" class="proposal confirmed">
              <header class="proposal-head">
                <AppIcon name="check" :size="15" />
                <strong>Justificat</strong>
                <button class="btn btn-ghost btn-sm undo" type="button" @click="decide.mutate({ kind: 'undo' })">Desfés</button>
              </header>
              <article v-for="match in confirmed.matches" :key="match.id" class="invoice">
                <RouterLink class="inv-main" :to="{ name: 'document', params: { internalDocNumber: match.document.num_doc_intern } }">
                  <strong>{{ match.document.num_factura || 'Sense número' }}</strong>
                  <span>{{ match.document.proveidor }}</span>
                </RouterLink>
                <span class="inv-meta mono">{{ formatDate(match.document.data_factura) }} · {{ formatAmount(match.document.import_value) }}</span>
                <button
                  v-if="match.document.file_url"
                  class="thumb"
                  :class="{ on: peekOpen && peekDoc?.num_doc_intern === match.document.num_doc_intern }"
                  type="button"
                  title="Mostra l'original (O)"
                  @click="showOriginal(match.document)"
                >
                  <img v-if="thumb(match.document)" :src="thumb(match.document) as string" alt="" />
                  <span v-else class="thumb-file">{{ thumbLabel(match.document) }}</span>
                </button>
              </article>
            </section>

            <!-- Proposal -->
            <section v-else-if="viewed" class="proposal" :class="band(viewed.confidence)">
              <header class="proposal-head">
                <span class="big">{{ viewed.confidence }}</span>
                <span class="band-label">{{ BAND_LABEL[band(viewed.confidence)] }}</span>
                <span v-if="viewed === lead" class="decided muted">{{ DECIDED_LABEL[viewedMatch?.decided_by ?? ''] ?? viewedMatch?.decided_by }}</span>
                <template v-else>
                  <span class="decided muted">{{ lead ? 'Alternativa' : 'Candidata' }}</span>
                  <button class="btn btn-ghost btn-sm back" type="button" @click="focusKey = null">{{ lead ? 'Torna a la proposta' : 'Tanca' }}</button>
                </template>
              </header>
              <p v-if="viewed.matches.length > 1" class="set-note">
                Un sol pagament de {{ viewed.matches.length }} factures que sumen l'import.
              </p>
              <article v-for="match in viewed.matches" :key="match.id" class="invoice">
                <RouterLink class="inv-main" :to="{ name: 'document', params: { internalDocNumber: match.document.num_doc_intern } }">
                  <strong>{{ match.document.num_factura || 'Sense número' }}</strong>
                  <span>{{ match.document.proveidor || 'Proveïdor desconegut' }}</span>
                </RouterLink>
                <span class="inv-meta mono">
                  {{ formatDate(match.document.data_factura) }} · {{ formatAmount(match.document.import_value) }}
                </span>
                <span class="inv-meta muted">
                  {{ match.document.cif_proveidor || 'sense CIF' }}
                  <template v-if="match.document.compte"> · {{ match.document.compte }}</template>
                  <template v-if="match.document.metode_pagament"> · {{ match.document.metode_pagament }}</template>
                </span>
                <button
                  v-if="match.document.file_url"
                  class="thumb"
                  :class="{ on: peekOpen && peekDoc?.num_doc_intern === match.document.num_doc_intern }"
                  type="button"
                  title="Mostra l'original (O)"
                  @click="showOriginal(match.document)"
                >
                  <img v-if="thumb(match.document)" :src="thumb(match.document) as string" alt="" />
                  <span v-else class="thumb-file">{{ thumbLabel(match.document) }}</span>
                </button>
              </article>
              <div class="signals">
                <span
                  v-for="key in SIGNALS"
                  :key="key"
                  class="signal"
                  :class="signalTone(viewedMatch?.signals[key])"
                >
                  {{ signalText(key, viewedMatch as PaymentMatch) }}
                  {{ signalTone(viewedMatch?.signals[key]) === 'on' ? '✓' : signalTone(viewedMatch?.signals[key]) === 'part' ? '~' : '—' }}
                </span>
              </div>
              <p v-if="viewedMatch?.reason" class="reason">{{ viewedMatch.reason }}</p>
              <details v-if="viewedMatch?.ai_trace?.openai" class="trace">
                <summary>Com s'hi ha arribat</summary>
                <dl>
                  <dt>gpt-6-luna</dt>
                  <dd>
                    {{ viewedMatch.ai_trace.openai.answer?.choice ?? viewedMatch.ai_trace.openai.status }}
                    · {{ pct(viewedMatch.ai_trace.openai.answer?.confidence) }}
                    <span class="muted">{{ viewedMatch.ai_trace.openai.answer?.reason }}</span>
                  </dd>
                  <dt>Jev</dt>
                  <dd>
                    <template v-if="viewedMatch.ai_trace.jev?.answer">
                      {{ viewedMatch.ai_trace.jev.answer.choice }} · {{ pct(viewedMatch.ai_trace.jev.answer.confidence) }}
                    </template>
                    <span v-else class="muted">{{ viewedMatch.ai_trace.jev?.status === 'off' ? 'No configurat' : viewedMatch.ai_trace.jev?.status }}</span>
                  </dd>
                  <dt>Candidates</dt>
                  <dd>{{ viewedMatch.ai_trace.candidates?.length ?? 0 }} factures possibles</dd>
                </dl>
              </details>
              <div class="decide">
                <button class="btn btn-primary" type="button" :disabled="decide.isPending.value" @click="confirmGroup(viewed)">
                  <AppIcon name="check" /> Confirmar
                </button>
                <button
                  class="btn btn-outline"
                  type="button"
                  :disabled="decide.isPending.value"
                  @click="decide.mutate({ kind: 'not-this', matchId: viewed.matches[0].id })"
                >
                  No és aquesta
                </button>
                <button class="btn btn-ghost" type="button" :disabled="decide.isPending.value" @click="decide.mutate({ kind: 'reject' })">
                  Cap factura
                </button>
              </div>
            </section>

            <!-- No proposal -->
            <section v-if="!viewed && detail.categoria === 'pagament' && !confirmed" class="proposal none">
              <header class="proposal-head">
                <strong>{{ STATUS_LABEL[detail.match_status] }}</strong>
              </header>
              <p class="muted">
                <template v-if="detail.match_status === 'unmatched'">Encara no s'ha buscat. Prem «Començar justificació».</template>
                <template v-else-if="detail.match_status === 'rejected'">Marcat sense factura.</template>
                <template v-else>Cap factura del registre encaixa prou. Pots triar una alternativa o buscar-la.</template>
              </p>
              <div class="decide">
                <button
                  v-if="detail.match_status !== 'rejected'"
                  class="btn btn-outline btn-sm"
                  type="button"
                  :disabled="decide.isPending.value"
                  @click="decide.mutate({ kind: 'repropose' })"
                >
                  <AppIcon name="sparkle" :size="13" />
                  {{ decide.isPending.value ? 'Buscant…' : detail.match_status === 'unmatched' ? 'Proposa només aquest' : 'Torna a proposar' }}
                </button>
                <button v-if="detail.match_status === 'rejected'" class="btn btn-ghost btn-sm" type="button" @click="decide.mutate({ kind: 'undo' })">
                  Desfés
                </button>
                <button
                  v-else-if="detail.match_status !== 'unmatched'"
                  class="btn btn-ghost btn-sm"
                  type="button"
                  @click="decide.mutate({ kind: 'reject' })"
                >
                  Cap factura
                </button>
              </div>
            </section>

            <!-- Alternatives -->
            <section v-if="alternatives.length && !confirmed" class="alternatives">
              <h3 class="section-title">{{ viewed === lead ? 'Altres candidates' : 'Candidates' }}</h3>
              <article v-for="group in alternatives" :key="group.key" class="alt">
                <span class="pill" :class="band(group.confidence)"><i class="dot" :class="band(group.confidence)" />{{ group.confidence }}</span>
                <span class="alt-text">
                  <template v-for="(match, i) in group.matches" :key="match.id">
                    <span v-if="i" class="muted"> + </span>
                    <strong>{{ match.document.num_factura || 'Sense número' }}</strong>
                    <span class="muted"> {{ match.document.proveidor }} · {{ formatDate(match.document.data_factura) }} · {{ formatAmount(match.document.import_value) }}</span>
                  </template>
                  <span v-if="group === lead" class="tag">Proposta</span>
                  <span v-if="group.matches[0].reason" class="alt-reason muted">{{ group.matches[0].reason }}</span>
                </span>
                <span class="alt-actions">
                  <button class="btn btn-ghost btn-sm" type="button" title="Compara-la amb el moviment" @click="focusKey = group.key">
                    <AppIcon name="info" :size="13" /> Detalls
                  </button>
                  <button class="btn btn-outline btn-sm" type="button" :disabled="decide.isPending.value" @click="confirmGroup(group)">
                    Confirmar
                  </button>
                </span>
              </article>
            </section>

            <!-- Manual -->
            <section v-if="detail.categoria === 'pagament' && !confirmed" class="manual">
              <h3 class="section-title">Buscar una altra factura</h3>
              <input v-model="search" class="input" type="search" placeholder="Número, proveïdor, CIF o import…" />
              <ul v-if="searchResults.length" class="results">
                <li v-for="doc in searchResults" :key="doc.num_doc_intern">
                  <span class="alt-text">
                    <strong>{{ doc.num_factura || 'Sense número' }}</strong>
                    <span class="muted"> {{ doc.proveidor }} · {{ formatDate(doc.data_factura) }} · {{ formatAmount(doc.import_value) }}</span>
                  </span>
                  <button
                    class="btn btn-ghost btn-sm"
                    type="button"
                    :disabled="decide.isPending.value"
                    @click="decide.mutate({ kind: 'confirm', refs: [doc.num_doc_intern] })"
                  >
                    <AppIcon name="link" :size="13" /> Vincula
                  </button>
                </li>
              </ul>
            </section>
          </template>
        </div>
      </section>
    </template>

    <MovementCard
      v-for="card in pinned"
      :key="`pin-${card.movement.id}`"
      :movement="card.movement"
      :x="card.x"
      :y="card.y"
      pinned
      @close="unpin(card)"
      @move="(x, y) => Object.assign(card, { x, y })"
    />
    <MovementCard
      v-if="hoverCard"
      :movement="hoverCard.movement"
      :x="hoverCard.x"
      :y="hoverCard.y"
      :pinned="false"
      @enter="cardEnter"
      @leave="rowLeave"
      @pin="hoverCard && pin(hoverCard)"
    />

    <DocumentPeek
      v-if="peekOpen"
      :src="peekFile?.url ?? null"
      :type="peekFile?.type ?? ''"
      :loading="!!peekDoc && originals.get(peekDoc.num_doc_intern) === 'loading'"
      :title="peekDoc ? peekDoc.num_factura || 'Sense número' : 'Cap factura proposada'"
      :subtitle="peekDoc ? `${peekDoc.proveidor} · ${formatDate(peekDoc.data_factura)} · ${formatAmount(peekDoc.import_value)}` : ''"
      :home="peekHome"
      @close="peekOpen = false"
    />
  </div>
</template>

<style scoped>
.reconcile {
  --band-high: var(--olive-700);
  --band-high-bg: var(--olive-100);
  --band-medium: var(--gold-800);
  --band-medium-bg: var(--gold-100);
  --band-low: var(--danger-700);
  --band-low-bg: var(--danger-100);
  --band-none: var(--ink-400);

  display: grid;
  grid-template-columns: minmax(0, 1fr);
  gap: 16px;
  max-width: 1320px;
}

/* ── Toolbar ─────────────────────────────────────────────────────────────── */
.toolbar {
  display: grid;
  gap: 8px;
  padding: 12px 14px;
}

.toolbar-main {
  display: flex;
  align-items: center;
  gap: 16px;
  flex-wrap: wrap;
}

/* ── Statement strip ─────────────────────────────────────────────────────── */
.type-row {
  display: flex;
  align-items: center;
  gap: 12px;
  min-width: 0;
}

.type-chips {
  display: flex;
  gap: 6px;
  overflow-x: auto;
  scrollbar-width: none;
  min-width: 0;
}

.type-chips .chip {
  white-space: nowrap;
}

.type-chips .chip:disabled {
  opacity: 0.45;
  cursor: default;
}

.pending-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--accent-600);
}

.strip-nav {
  display: flex;
  gap: 2px;
  margin-left: auto;
}

.flip {
  transform: rotate(180deg);
}

.strip {
  display: flex;
  gap: 8px;
  overflow-x: auto;
  padding: 2px 2px 6px;
  scroll-snap-type: x proximity;
  scrollbar-width: thin;
  /* Fade the far edge so it reads as "more this way". */
  mask-image: linear-gradient(to right, #000 calc(100% - 40px), transparent);
}

.st {
  flex: 0 0 208px;
  display: grid;
  gap: 4px;
  padding: 8px 10px;
  text-align: left;
  scroll-snap-align: start;
  background: var(--surface-0);
  border: 1px solid var(--line);
  border-radius: var(--r-md);
  transition:
    border-color 0.12s ease,
    box-shadow 0.12s ease;
}

.st > * {
  width: 100%;
  min-width: 0;
}

.st:hover {
  border-color: var(--line-strong);
}

.st.empty {
  background: var(--surface-1);
  color: var(--ink-400);
}

.st.empty strong {
  color: var(--ink-500);
}

.st.on {
  border-color: var(--accent-500);
  box-shadow: 0 0 0 1px var(--accent-500);
}

.st-top {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 6px;
  min-width: 0;
}

.st-source {
  flex: none;
  font-size: var(--text-xs);
  color: var(--ink-400);
}

.st-period {
  font-size: var(--text-sm);
  color: var(--ink-700);
}

.st-bar {
  height: 3px;
  border-radius: var(--r-full);
  background: var(--surface-2);
  overflow: hidden;
}

.st-bar span {
  display: block;
  height: 100%;
  background: var(--olive-700);
}

.st-foot {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 6px;
  font-size: var(--text-xs);
  color: var(--ink-500);
  font-variant-numeric: tabular-nums;
}

.st-dots {
  display: inline-flex;
  align-items: center;
  gap: 3px;
}

.st-dots .dot {
  width: 6px;
  height: 6px;
  margin-left: 4px;
}

.st-ok {
  display: inline-flex;
  color: var(--olive-700);
}

.picker-label,
.section-title {
  flex: none;
  margin: 0;
  font-size: var(--text-xs);
  font-weight: 600;
  letter-spacing: 0.06em;
  text-transform: uppercase;
  color: var(--ink-400);
}

.progress-block {
  display: grid;
  gap: 6px;
  flex: 1;
  min-width: 260px;
}

.progress-line {
  display: flex;
  justify-content: space-between;
  gap: 8px;
  font-size: var(--text-sm);
  font-variant-numeric: tabular-nums;
}

.bands {
  display: inline-flex;
  gap: 10px;
}

.band-count {
  display: inline-flex;
  align-items: center;
  gap: 4px;
}

.bar {
  height: 6px;
  border-radius: var(--r-full);
  background: var(--surface-2);
  overflow: hidden;
}

.bar span {
  display: block;
  height: 100%;
  background: var(--olive-700);
  transition: width 0.3s ease;
}

.bar.small {
  width: 120px;
  height: 4px;
}

.bar.small span {
  background: var(--accent-600);
}

.start {
  white-space: nowrap;
}

.start-count {
  min-width: 18px;
  padding: 0 5px;
  border-radius: var(--r-full);
  background: rgb(255 255 255 / 0.25);
  font-size: var(--text-xs);
  font-weight: 700;
  line-height: 18px;
  text-align: center;
}

.run-progress {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  font-size: var(--text-sm);
  font-variant-numeric: tabular-nums;
  color: var(--accent-700);
}

.run-done {
  margin: 0;
  font-size: var(--text-sm);
}

/* ── Dots, pills and bands ──────────────────────────────────────────────── */
.dot {
  display: inline-block;
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: var(--band-none);
}

.dot.high {
  background: var(--band-high);
}

.dot.medium {
  background: var(--gold-500);
}

.dot.low {
  background: var(--band-low);
}

.pill {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  padding: 1px 7px;
  border-radius: var(--r-full);
  font-size: var(--text-xs);
  font-weight: 600;
  font-variant-numeric: tabular-nums;
  border: 1px solid var(--line);
  background: var(--surface-0);
}

.pill.high {
  color: var(--band-high);
}

.pill.medium {
  color: var(--band-medium);
}

.pill.low {
  color: var(--band-low);
}

/* ── Panes ──────────────────────────────────────────────────────────────── */
.panes {
  display: grid;
  grid-template-columns: minmax(0, 1.05fr) minmax(0, 1fr);
  gap: 16px;
  align-items: start;
}

.list {
  display: grid;
  gap: 8px;
  padding: 10px;
  container-type: inline-size;
}

.chips {
  display: flex;
  gap: 6px;
}

.chip {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 3px 10px;
  border: 1px solid var(--line);
  border-radius: var(--r-full);
  background: var(--surface-0);
  font-size: var(--text-sm);
  color: var(--ink-700);
}

.chip span {
  font-variant-numeric: tabular-nums;
  color: var(--ink-400);
}

.chip.on {
  border-color: var(--accent-500);
  color: var(--accent-700);
}

.movements {
  display: grid;
  margin: 0;
  padding: 0;
  list-style: none;
  max-height: calc(100vh - 330px);
  min-height: 200px;
  overflow-y: auto;
}

.movement {
  display: grid;
  grid-template-columns: 74px minmax(0, 1fr) auto 92px;
  align-items: center;
  gap: 10px;
  padding: 6px 8px 6px 10px;
  border-left: 3px solid transparent;
  border-bottom: 1px solid var(--line);
  cursor: pointer;
  font-size: var(--text-sm);
}

.movement:hover {
  background: var(--surface-1);
}

.movement.selected {
  background: var(--accent-100);
}

.movement.band-high {
  border-left-color: var(--band-high);
}

.movement.band-medium {
  border-left-color: var(--gold-500);
}

.movement.band-low {
  border-left-color: var(--band-low);
}

.m-text {
  display: grid;
  min-width: 0;
  line-height: 1.3;
}

.m-date,
.m-amount {
  display: grid;
  line-height: 1.3;
}

.m-text .muted,
.m-ref,
.m-saldo {
  font-size: var(--text-xs);
}

.m-amount {
  justify-items: end;
  font-variant-numeric: tabular-nums;
  white-space: nowrap;
}

.m-state {
  justify-self: end;
}

.state-confirmed {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 1px 7px;
  border-radius: var(--r-full);
  background: var(--olive-700);
  color: #fff;
  font-size: var(--text-xs);
  font-weight: 600;
}

.state-plain {
  font-size: var(--text-xs);
  color: var(--ink-400);
}

.others {
  display: grid;
  gap: 4px;
}

.movements.dim .movement {
  color: var(--ink-400);
}

.rotated {
  transform: rotate(90deg);
}

.keys {
  margin: 0;
  font-size: var(--text-xs);
}

/* ── Side ───────────────────────────────────────────────────────────────── */
.side {
  display: grid;
  gap: 12px;
  padding: 14px;
  position: sticky;
  top: 12px;
}

.mv {
  display: grid;
  gap: 4px;
  padding-bottom: 10px;
  border-bottom: 1px solid var(--line);
}

.mv-top {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
}

.mv-date {
  display: inline-flex;
  align-items: center;
  gap: 4px;
}

.mv-date .on {
  color: var(--accent-700);
}

.mv-amount {
  font-size: var(--text-xl);
  font-weight: 600;
  font-variant-numeric: tabular-nums;
}

.mv-amount.in {
  color: var(--olive-700);
}

.mv-concept {
  font-weight: 500;
}

.mv-facts {
  display: flex;
  flex-wrap: wrap;
  gap: 2px 14px;
  font-size: var(--text-sm);
  font-variant-numeric: tabular-nums;
}

.mv-meta {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 6px;
  font-size: var(--text-sm);
}

.proposal {
  display: grid;
  gap: 8px;
  padding: 0 12px 12px;
  border: 1px solid var(--line);
  border-radius: var(--r-lg);
  overflow: hidden;
}

.proposal-head {
  display: flex;
  align-items: center;
  gap: 10px;
  margin: 0 -12px;
  padding: 8px 12px;
  background: var(--surface-1);
  border-bottom: 1px solid var(--line);
}

.proposal.high .proposal-head {
  background: var(--band-high-bg);
  color: var(--band-high);
}

.proposal.medium .proposal-head {
  background: var(--band-medium-bg);
  color: var(--band-medium);
}

.proposal.low .proposal-head {
  background: var(--band-low-bg);
  color: var(--band-low);
}

.proposal.confirmed .proposal-head {
  background: var(--olive-700);
  color: #fff;
}

.proposal.confirmed .undo {
  margin-left: auto;
  color: #fff;
}

.big {
  font-size: var(--text-2xl);
  font-weight: 700;
  font-variant-numeric: tabular-nums;
  line-height: 1;
}

.band-label {
  font-weight: 600;
}

.decided {
  margin-left: auto;
  font-size: var(--text-xs);
}

.set-note {
  margin: 0;
  font-size: var(--text-sm);
  color: var(--gold-800);
}

.invoice {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  gap: 2px 8px;
  padding: 6px 0;
  border-bottom: 1px dashed var(--line);
}

.inv-main {
  display: grid;
  color: inherit;
}

.inv-main:hover strong {
  color: var(--accent-700);
}

.inv-meta {
  grid-column: 1;
  font-size: var(--text-sm);
}

.thumb {
  grid-column: 2;
  grid-row: 1 / span 3;
  align-self: start;
  display: grid;
  place-items: center;
  width: 60px;
  height: 76px;
  padding: 0;
  overflow: hidden;
  border: 1px solid var(--line);
  border-radius: var(--r-sm);
  background: var(--surface-1);
  cursor: zoom-in;
  transition:
    border-color 0.12s ease,
    box-shadow 0.12s ease;
}

.thumb:hover {
  border-color: var(--line-strong);
}

.thumb.on {
  border-color: var(--accent-500);
  box-shadow: 0 0 0 1px var(--accent-500);
}

.thumb img {
  width: 100%;
  height: 100%;
  object-fit: cover;
  object-position: top;
}

.thumb-file {
  font-size: var(--text-xs);
  font-weight: 600;
  color: var(--ink-500);
}

.signals {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
}

.signal {
  padding: 1px 7px;
  border-radius: var(--r-sm);
  font-size: var(--text-xs);
  border: 1px solid var(--line);
  color: var(--ink-400);
}

.signal.on {
  color: var(--ink-700);
  border-color: var(--line-strong);
}

.signal.part {
  color: var(--ink-500);
}

.reason {
  margin: 0;
  font-size: var(--text-sm);
  color: var(--ink-700);
}

.trace {
  font-size: var(--text-sm);
}

.trace summary {
  cursor: pointer;
  color: var(--ink-500);
}

.trace dl {
  display: grid;
  grid-template-columns: auto 1fr;
  gap: 4px 10px;
  margin: 6px 0 0;
}

.trace dt {
  font-weight: 600;
}

.trace dd {
  margin: 0;
}

.decide {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.alternatives,
.manual {
  display: grid;
  gap: 6px;
}

.alt,
.results li {
  display: grid;
  grid-template-columns: auto minmax(0, 1fr) auto;
  align-items: center;
  gap: 8px;
  font-size: var(--text-sm);
}

.results {
  display: grid;
  gap: 4px;
  margin: 0;
  padding: 0;
  list-style: none;
}

.results li {
  grid-template-columns: minmax(0, 1fr) auto;
}

.alt-text {
  min-width: 0;
}

.alt-text strong {
  margin-right: 4px;
}

.alt-actions {
  display: inline-flex;
  gap: 4px;
}

.tag {
  margin-left: 6px;
  padding: 0 5px;
  border: 1px solid var(--line);
  border-radius: var(--r-sm);
  font-size: var(--text-xs);
  color: var(--ink-500);
}

.back {
  color: inherit;
}

.alt-reason {
  display: block;
  font-size: var(--text-xs);
}

.spin {
  animation: spin 0.9s linear infinite;
}

@keyframes spin {
  to {
    transform: rotate(360deg);
  }
}

@media (max-width: 1000px) {
  .panes {
    grid-template-columns: minmax(0, 1fr);
  }

  .side {
    position: static;
  }

  .movements {
    max-height: 420px;
  }

  .type-row {
    flex-wrap: wrap;
  }
}

@container (max-width: 440px) {
  .movement {
    grid-template-columns: 70px minmax(0, 1fr) auto;
    gap: 2px 8px;
  }

  .m-date {
    font-size: var(--text-xs);
  }

  .m-date .mono {
    font-size: inherit;
  }

  .m-date {
    grid-column: 1;
    grid-row: 1 / span 2;
  }

  .m-text {
    grid-column: 2;
    grid-row: 1 / span 2;
  }

  .m-amount {
    grid-column: 3;
    grid-row: 1;
    justify-self: end;
  }

  .m-state {
    grid-column: 3;
    grid-row: 2;
  }
}
</style>
