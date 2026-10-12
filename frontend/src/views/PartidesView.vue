<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { RouterLink, useRoute, useRouter } from 'vue-router'
import { useQuery, useQueryClient } from '@tanstack/vue-query'

import { ApiError, api } from '../api/client'
import type { Partida, PartidaInvoice, PartidaQueueItem, Pressupost } from '../api/types'
import AppIcon from '../components/AppIcon.vue'
import DocumentPeek from '../components/DocumentPeek.vue'
import PartidaPicker from '../components/partides/PartidaPicker.vue'
import SplitEditor, { type SplitLine } from '../components/partides/SplitEditor.vue'
import { fold } from '../composables/useTableQuery'
import { formatAmount, formatDate } from '../document-fields'
import { type Share, addShare, evenShares, fundTone, lineTitle, lineYears, removeShare, shortCode } from '../partides'

/**
 * Charging statement movements to budget lines, one after another, fast.
 *
 * esfer@ books the money that moved, so what is charged is a line of an
 * extract — the bank, the caixeta, the prepaid card. The queue down the left;
 * the movement — concept, amount, account — and the invoices it paid (who,
 * what for in the AI's words and the teacher's), which are what tell the
 * line, in the middle; the budget as a map on the right. Jev proposes in
 * violet before a person decides; nothing it proposes counts until it is
 * saved here.
 *
 * The secretari/a's alone: the route and every write check it.
 */
const route = useRoute()
const router = useRouter()
const queryClient = useQueryClient()

const queueQuery = useQuery({ queryKey: ['partides-queue'], queryFn: api.getPartidesQueue })
const queue = computed(() => queueQuery.data.value ?? [])

// ── The queue ───────────────────────────────────────────────────────────────

type Tab = 'pendent' | 'proposta' | 'assignada' | 'totes'
const TABS: { id: Tab; label: string }[] = [
  { id: 'pendent', label: 'Pendents' },
  { id: 'proposta', label: 'Propostes' },
  { id: 'assignada', label: 'Fetes' },
  { id: 'totes', label: 'Totes' },
]
const tab = ref<Tab>('pendent')
const railSearch = ref('')

// ── Which account ───────────────────────────────────────────────────────────
// The same chips as Justificar extractes, and the same `?compte=` in the URL.

const ACCOUNTS = ['General', 'Material i Sortides', 'Menjador', 'Targeta Prepagament', 'Caixeta']
const account = computed(() => (typeof route.query.compte === 'string' ? route.query.compte : ''))
const accountChips = computed(() =>
  ACCOUNTS.map((name) => {
    const own = queue.value.filter((item) => item.compte === name)
    return { name, count: own.length, pending: own.filter((item) => item.estat !== 'assignada').length }
  }),
)
const scoped = computed(() => (account.value ? queue.value.filter((item) => item.compte === account.value) : queue.value))

function pickAccount(name: string) {
  if (dirty.value && !window.confirm('Aquest moviment té canvis sense desar. Vols descartar-los?')) return
  const query = { ...route.query }
  delete query.m
  if (name && name !== account.value) query.compte = name
  else delete query.compte
  void router.replace({ query })
}

const counts = computed(() => {
  const result: Record<Tab, number> = { pendent: 0, proposta: 0, assignada: 0, totes: scoped.value.length }
  for (const item of scoped.value) result[item.estat] += 1
  return result
})

/**
 * The list as it was when the tab or the search last changed. Saving a
 * movement moves it to "Fets", but it stays where it was here, so "next" is
 * the one that was next — the same rule as the register's window.
 */
const frozen = ref<number[]>([])
function refreeze() {
  const words = fold(railSearch.value)
  frozen.value = scoped.value
    .filter((item) => tab.value === 'totes' || item.estat === tab.value)
    .filter(
      (item) =>
        !words ||
        fold(
          [
            item.concepte,
            item.mes_dades,
            item.codi,
            item.compte,
            ...item.factures.flatMap((f) => [f.proveidor, f.descripcio, f.descripcio_compra, f.num_factura]),
          ].join(' '),
        ).includes(words),
    )
    .map((item) => item.id)
}
watch([tab, railSearch], refreeze)
// Another account: its list, and its first movement.
watch(account, () => {
  refreeze()
  if (frozen.value.length) open(frozen.value[0], true)
})

const byRef = computed(() => new Map(queue.value.map((item) => [item.id, item])))
const rail = computed(() => frozen.value.map((id) => byRef.value.get(id)).filter(Boolean) as PartidaQueueItem[])

const currentRef = computed(() => Number(route.query.m) || null)
const current = computed(() => (currentRef.value ? (byRef.value.get(currentRef.value) ?? null) : null))
const position = computed(() => (currentRef.value ? frozen.value.indexOf(currentRef.value) : -1))
const nextRef = computed(() => (position.value >= 0 ? frozen.value[position.value + 1] : frozen.value[0]))
const prevRef = computed(() => (position.value > 0 ? frozen.value[position.value - 1] : undefined))

function open(id: number | undefined, replace = false) {
  if (!id || id === currentRef.value) return
  if (dirty.value && !window.confirm('Aquest moviment té canvis sense desar. Vols descartar-los?')) return
  const to = { query: { ...route.query, m: String(id) } }
  void (replace ? router.replace(to) : router.push(to))
}

/** What the rail calls a movement: who was paid, when an invoice says so; the bank's words if not. */
function railName(item: PartidaQueueItem) {
  return item.factures[0]?.proveidor || item.concepte || 'Sense concepte'
}

/** Parts are always positive, whichever way the money went. */
const total = computed(() => (current.value ? Math.abs(current.value.import_value) : null))

// ── The budget for this movement's year ─────────────────────────────────────

const exercici = computed(() => current.value?.exercici ?? null)
const budgetQuery = useQuery({
  queryKey: computed(() => ['pressupost', exercici.value]),
  queryFn: () => api.getPressupost(exercici.value),
})
const budget = computed(() => budgetQuery.data.value)
const lines = computed(() => budget.value?.partides ?? [])
const lineById = computed(() => new Map(lines.value.map((p) => [p.id, p])))
const noBudget = computed(() => budgetQuery.isSuccess.value && budget.value?.exercici == null)
const jevOn = computed(() => Boolean(budget.value?.jev))

// ── What this movement is charged to (the draft) ────────────────────────────

const draft = ref<Share[]>([])
const savedKey = ref('')

function keyOf(list: Share[]) {
  return JSON.stringify(list.map((line) => [line.id, list.length > 1 ? line.amount : null]))
}

function loadDraft(item: PartidaQueueItem | null) {
  draft.value = (item?.assignments ?? []).map((a) => ({ id: a.partida_id, amount: a.import_assignat }))
  if (draft.value.length > 1 && draft.value.some((line) => line.amount == null)) {
    draft.value = evenShares(draft.value.map((line) => line.id), total.value)
  }
  // Jev's proposal is not saved yet: it starts dirty, so one keystroke confirms it.
  savedKey.value = item?.assignments.every((a) => a.confirmada) ? keyOf(draft.value) : ''
}

const dirty = computed(() => keyOf(draft.value) !== savedKey.value && (draft.value.length > 0 || savedKey.value !== ''))
watch(() => current.value?.id, () => loadDraft(current.value), { immediate: true })
// A refetch updates the draft only while nobody is editing it.
watch(current, (item, old) => {
  if (item && old && item.id === old.id && !dirty.value) loadDraft(item)
})

const unconfirmed = computed(
  () => new Set((current.value?.assignments ?? []).filter((a) => !a.confirmada).map((a) => a.partida_id)),
)
/** Jev's proposal, exactly as it came: not saved, but not touched either. */
const proposalAsIs = computed(() => {
  const item = current.value
  if (!item || !unconfirmed.value.size) return false
  const proposed = item.assignments.map((a) => a.partida_id).sort()
  const now = draft.value.map((line) => line.id).sort()
  return proposed.join() === now.join()
})

function toggle(id: number) {
  const line = lineById.value.get(id)
  if (!line || line.te_fills) return
  draft.value = draft.value.some((d) => d.id === id)
    ? removeShare(draft.value, id, total.value)
    : addShare(draft.value, id, total.value)
}


const splitLines = computed<SplitLine[]>(() =>
  draft.value.map((line) => {
    const partida = lineById.value.get(line.id)
    const tone = fundTone(partida?.fons ?? '')
    return {
      id: line.id,
      title: partida ? lineTitle(partida.nom) : `Partida ${line.id}`,
      code: partida ? `${lineYears(partida.nom)[0] ?? ''} ${shortCode(partida.codi)}`.trim() : '',
      fund: partida?.codi_finalista ? partida.fons_label : '',
      colour: tone.solid,
      soft: tone.soft,
      jev: unconfirmed.value.has(line.id) && proposalAsIs.value,
    }
  }),
)

const splitBalanced = computed(() => {
  if (draft.value.length < 2) return true
  const whole = total.value
  const sum = draft.value.reduce((acc, line) => acc + (line.amount ?? 0), 0)
  if (draft.value.some((line) => !line.amount || line.amount <= 0)) return false
  return whole == null || Math.abs(sum - whole) < 0.005
})

// First load (or a cached one): start on the pending ones, or everything if
// none are. Declared here, after everything `open` reads.
watch(
  () => queueQuery.data.value,
  (data, old) => {
    if (!data || old) return
    const linked = data.find((item) => item.id === currentRef.value)
    if (linked) tab.value = linked.estat
    else if (!data.some((item) => item.estat === 'pendent')) {
      tab.value = data.some((item) => item.estat === 'proposta') ? 'proposta' : 'totes'
    }
    refreeze()
    if (!currentRef.value && frozen.value.length) open(frozen.value[0], true)
  },
  { immediate: true },
)

// ── The secretari/a's order of the lines ────────────────────────────────────

const order = computed(() => budget.value?.ordre_usuari ?? {})

async function reorder(block: string, codis: string[]) {
  const key = ['pressupost', exercici.value]
  const before = queryClient.getQueryData<Pressupost>(key)
  if (before) queryClient.setQueryData<Pressupost>(key, { ...before, ordre_usuari: { ...before.ordre_usuari, [block]: codis } })
  try {
    const saved = await api.updatePartidesOrder(block, codis)
    queryClient.setQueriesData<Pressupost>({ queryKey: ['pressupost'] }, (data) => (data ? { ...data, ordre_usuari: saved } : data))
  } catch (error) {
    if (before) queryClient.setQueryData(key, before)
    saveError.value = error instanceof Error ? error.message : String(error)
  }
}

// ── Columns ─────────────────────────────────────────────────────────────────
// The three columns part where people drag them, and stay that way.

const COLUMNS_KEY = 'cosecre.partides.columns.v2'
// The map is what is worked in, so it gets the most room; then the movement; then the list.
const columns = reactive({ rail: 220, middle: 360 })
try {
  Object.assign(columns, JSON.parse(localStorage.getItem(COLUMNS_KEY) ?? '{}'))
} catch {
  // A blocked or broken store: the defaults will do.
}

function startResize(event: PointerEvent, which: 'rail' | 'middle') {
  if (event.button !== 0) return
  const handle = event.currentTarget as HTMLElement
  handle.setPointerCapture(event.pointerId)
  const startX = event.clientX
  const start = columns[which]
  const [min, max] = which === 'rail' ? [180, 360] : [300, 640]
  const move = (e: PointerEvent) => {
    columns[which] = Math.round(Math.min(max, Math.max(min, start + e.clientX - startX)))
  }
  const up = () => {
    handle.removeEventListener('pointermove', move)
    handle.removeEventListener('pointerup', up)
    try {
      localStorage.setItem(COLUMNS_KEY, JSON.stringify(columns))
    } catch {
      // Not kept; it still applies until the page is left.
    }
  }
  handle.addEventListener('pointermove', move)
  handle.addEventListener('pointerup', up)
  event.preventDefault()
}

// ── Saving ──────────────────────────────────────────────────────────────────

const saving = ref(false)
const saveError = ref('')

function replaceItem(item: PartidaQueueItem) {
  queryClient.setQueryData<PartidaQueueItem[]>(['partides-queue'], (list) =>
    list?.map((existing) => (existing.id === item.id ? item : existing)),
  )
}

async function save(advance: boolean) {
  const item = current.value
  if (!item || saving.value || !splitBalanced.value) return
  const target = advance ? nextRef.value : undefined
  saving.value = true
  saveError.value = ''
  try {
    const saved = await api.assignPartides(
      item.id,
      draft.value.map((line) => ({ partida_id: line.id, import_assignat: draft.value.length > 1 ? line.amount : null })),
    )
    replaceItem(saved)
    loadDraft(saved)
    void queryClient.invalidateQueries({ queryKey: ['pressupost'] })
    if (target) open(target)
  } catch (error) {
    saveError.value = error instanceof Error ? error.message : String(error)
  } finally {
    saving.value = false
  }
}

// ── Jev ─────────────────────────────────────────────────────────────────────

const asking = reactive(new Set<number>())
const bulk = reactive({ running: false, done: 0, total: 0, failed: 0, stop: false })
const askError = ref('')
const asked = new Set<number>()

async function askJev(id: number, quiet = false) {
  if (asking.has(id)) return
  asking.add(id)
  if (!quiet) askError.value = ''
  try {
    const item = await api.suggestPartides(id)
    replaceItem(item)
    if (item.id === currentRef.value && !dirty.value) loadDraft(item)
  } catch (error) {
    if (!quiet) askError.value = error instanceof ApiError ? error.message : String(error)
    throw error
  } finally {
    asking.delete(id)
  }
}

/** Open a pending movement nobody has asked about, and Jev is asked — and the next one too. */
watch(
  [current, jevOn, noBudget],
  () => {
    if (!jevOn.value || noBudget.value || bulk.running) return
    for (const id of [currentRef.value, nextRef.value]) {
      const item = id ? byRef.value.get(id) : undefined
      if (item && item.estat === 'pendent' && !item.suggestion && !asked.has(item.id)) {
        asked.add(item.id)
        void askJev(item.id, item.id !== currentRef.value).catch(() => undefined)
      }
    }
  },
  { immediate: true },
)

const suggestion = computed(() => current.value?.suggestion ?? null)
/** Only what Jev gave a real chance: a 0 % tag on a line is noise. */
const suggestedMap = computed<Record<number, number>>(() =>
  Object.fromEntries(
    (suggestion.value?.ranking ?? []).filter((r) => r.probability >= 0.02).map((r) => [r.partida_id, r.probability]),
  ),
)
const topSuggestions = computed(() =>
  (suggestion.value?.ranking ?? [])
    .filter((r) => r.probability >= 0.02)
    .slice(0, 3)
    .map((r) => ({ ...r, partida: lineById.value.get(r.partida_id) }))
    .filter((r): r is typeof r & { partida: Partida } => Boolean(r.partida)),
)

/** Every pending movement without a proposal, a few at a time. */
const bulkTargets = computed(() => queue.value.filter((item) => item.estat === 'pendent' && !item.suggestion))

async function proposeAll() {
  if (bulk.running) {
    bulk.stop = true
    return
  }
  const targets = bulkTargets.value.map((item) => item.id)
  Object.assign(bulk, { running: true, done: 0, total: targets.length, failed: 0, stop: false })
  const worker = async () => {
    while (targets.length && !bulk.stop) {
      const id = targets.shift()!
      asked.add(id)
      try {
        await askJev(id, true)
      } catch {
        bulk.failed += 1
      }
      bulk.done += 1
    }
  }
  await Promise.all([worker(), worker(), worker(), worker()])
  bulk.running = false
}

// ── The original ────────────────────────────────────────────────────────────

/** The invoice whose original floats over the map, by register reference. */
const peekRef = ref<string | null>(null)
const peekInvoice = computed<PartidaInvoice | null>(
  () => current.value?.factures.find((f) => f.reference === peekRef.value) ?? null,
)
const originals = reactive(new Map<string, { url: string; type: string } | 'loading' | 'missing'>())
const peekFile = computed(() => {
  const entry = peekRef.value ? originals.get(peekRef.value) : undefined
  return typeof entry === 'object' ? entry : null
})
const firstWithFile = computed(() => current.value?.factures.find((f) => f.file_url) ?? null)

function togglePeek(invoice: PartidaInvoice | null) {
  peekRef.value = invoice && peekRef.value !== invoice.reference ? invoice.reference : null
}

async function loadOriginal(invoice: PartidaInvoice | null) {
  if (!invoice?.file_url || originals.has(invoice.reference)) return
  originals.set(invoice.reference, 'loading')
  try {
    originals.set(invoice.reference, await api.getDocumentFile(invoice.reference))
  } catch {
    originals.set(invoice.reference, 'missing')
  }
}
watch(peekInvoice, (invoice) => void loadOriginal(invoice))
// Another movement, other invoices: a peek left open follows to its first one.
watch(
  () => current.value?.id,
  () => {
    if (peekRef.value) peekRef.value = firstWithFile.value?.reference ?? null
  },
)
onBeforeUnmount(() => {
  for (const entry of originals.values()) if (typeof entry === 'object') URL.revokeObjectURL(entry.url)
})

/** Over the budget map, which is what is least needed while reading the invoice. */
function peekHome() {
  const map = document.querySelector('.assign-map')?.getBoundingClientRect()
  if (!map) return { x: 16, y: 16, w: 440, h: 560 }
  return { x: map.left + 8, y: map.top, w: Math.min(520, map.width - 16), h: Math.min(window.innerHeight - map.top - 16, 760) }
}

// ── Keyboard ────────────────────────────────────────────────────────────────

const picker = ref<InstanceType<typeof PartidaPicker> | null>(null)

function inField(target: EventTarget | null) {
  return target instanceof HTMLElement && Boolean(target.closest('input, textarea, select, [contenteditable]'))
}

function onKey(event: KeyboardEvent) {
  if ((event.metaKey || event.ctrlKey) && event.key === 'Enter') {
    event.preventDefault()
    void save(!event.shiftKey)
    return
  }
  if (inField(event.target) || event.metaKey || event.ctrlKey || event.altKey) return
  if (event.key === '/') {
    event.preventDefault()
    picker.value?.focusSearch()
  } else if (event.key === 'j' || event.key === 'ArrowDown') {
    if (event.key === 'ArrowDown' && (event.target as HTMLElement)?.closest?.('.map')) return
    event.preventDefault()
    open(nextRef.value)
  } else if (event.key === 'k' || event.key === 'ArrowUp') {
    if (event.key === 'ArrowUp' && (event.target as HTMLElement)?.closest?.('.map')) return
    event.preventDefault()
    open(prevRef.value)
  } else if (['1', '2', '3'].includes(event.key)) {
    const pick = topSuggestions.value[Number(event.key) - 1]
    if (pick) toggle(pick.partida_id)
  } else if (event.key === 'o') {
    togglePeek(peekRef.value ? null : firstWithFile.value)
  } else if (event.key === 'p' && jevOn.value && currentRef.value) {
    void askJev(currentRef.value).catch(() => undefined)
  }
}

onMounted(() => window.addEventListener('keydown', onKey))
onBeforeUnmount(() => window.removeEventListener('keydown', onKey))

// The selected rail entry stays in view as j/k walk the queue.
watch(currentRef, (reference) => {
  requestAnimationFrame(() => document.querySelector(`[data-ref="${reference}"]`)?.scrollIntoView({ block: 'nearest' }))
})

const doneShare = computed(() => (scoped.value.length ? counts.value.assignada / scoped.value.length : 0))

function pct(value: number) {
  return `${Math.round(value * 100)} %`
}

/** Where the movement stands in Justificar extractes, when it is not confirmed. */
const JUSTIFICACIO: Record<string, string> = {
  unmatched: 'Encara no s’ha justificat amb cap factura.',
  proposed: 'Hi ha una factura proposada, pendent de confirmar a Justificar extractes.',
  no_match: 'No s’ha trobat cap factura que hi encaixi.',
  rejected: 'La factura proposada es va rebutjar.',
}

function signed(value: number) {
  return `${value > 0 ? '+' : ''}${formatAmount(value)}`
}
</script>

<template>
  <div class="partides">
    <header class="page-head">
      <div>
        <h1 class="page-title">Assignar partides</h1>
        <p class="page-lead">
          Cada moviment dels extractes, a la partida del pressupost{{ budget?.exercici ? ` ${budget.exercici}` : '' }} on s'imputa.
          <template v-if="budget?.centre"> · {{ budget.centre }}</template>
        </p>
      </div>
      <div class="head-side">
        <div class="progress-block" :title="`${counts.assignada} de ${counts.totes} moviments amb partida`">
          <span class="progress-label">
            <strong>{{ counts.assignada }}</strong>
            <span class="muted"> / {{ counts.totes }} fetes</span>
          </span>
          <span class="progress"><span :style="{ width: pct(doneShare) }" /></span>
        </div>
        <button
          v-if="jevOn && !noBudget"
          type="button"
          class="btn btn-ai btn-sm"
          :disabled="!bulk.running && bulkTargets.length === 0"
          :title="bulk.running ? 'Atura' : 'Jev proposa una partida per a cada moviment pendent; no es desa res fins que ho confirmis'"
          @click="proposeAll"
        >
          <AppIcon :name="bulk.running ? 'stop' : 'sparkles'" :size="14" />
          <template v-if="bulk.running">Proposant… {{ bulk.done }}/{{ bulk.total }}</template>
          <template v-else>Proposa les pendents{{ bulkTargets.length ? ` (${bulkTargets.length})` : '' }}</template>
        </button>
      </div>
    </header>

    <div class="accounts" role="group" aria-label="Filtra per compte">
      <button class="chip" :class="{ on: !account }" type="button" @click="pickAccount('')">
        Tots <span>{{ queue.length }}</span>
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
        <i v-if="chip.pending" class="pending-dot" :title="`${chip.pending} sense partida`" />
      </button>
    </div>

    <p v-if="noBudget" class="notice notice-info">
      <AppIcon name="info" :size="15" />
      <span>
        Encara no hi ha cap pressupost importat.
        <RouterLink :to="{ name: 'settings', query: { tab: 'pressupost' } }">Importa'l a Configuració</RouterLink>
        amb l'Excel d'esfer@.
      </span>
    </p>
    <p v-if="bulk.failed && !bulk.running" class="notice notice-error">
      <AppIcon name="alert" :size="15" />
      <span>Jev no ha pogut proposar {{ bulk.failed }} moviments. Torna-ho a provar.</span>
    </p>

    <div class="work" :style="{ '--rail-w': `${columns.rail}px`, '--middle-w': `${columns.middle}px` }">
      <!-- ── The queue ─────────────────────────────────────────────────── -->
      <aside class="rail card" aria-label="Moviments">
        <nav class="rail-tabs" role="tablist">
          <button
            v-for="option in TABS"
            :key="option.id"
            type="button"
            role="tab"
            class="rail-tab"
            :class="{ on: tab === option.id }"
            :aria-selected="tab === option.id"
            @click="tab = option.id"
          >
            {{ option.label }}
            <span class="rail-count">{{ counts[option.id] }}</span>
          </button>
        </nav>
        <input v-model="railSearch" class="input rail-search" type="search" placeholder="Concepte, proveïdor, descripció…" />
        <ul class="rail-list">
          <li v-if="queueQuery.isLoading.value" class="rail-empty">Carregant…</li>
          <li v-else-if="!rail.length" class="rail-empty">Res per aquí.</li>
          <li v-for="item in rail" :key="item.id">
            <button
              type="button"
              class="rail-item"
              :class="{ on: item.id === currentRef }"
              :data-ref="item.id"
              @click="open(item.id)"
            >
              <span class="state" :class="`state-${item.estat}`" :title="item.estat">
                <AppIcon v-if="item.estat === 'assignada'" name="check" :size="10" />
                <AppIcon v-else-if="item.estat === 'proposta'" name="sparkles" :size="10" />
                <AppIcon v-else-if="asking.has(item.id)" name="refresh" :size="10" class="spin" />
              </span>
              <span class="rail-main">
                <span class="rail-name truncate">{{ railName(item) }}</span>
                <span class="rail-sub truncate">
                  {{ item.factures.length ? item.factures[0].descripcio_compra || item.factures[0].descripcio || item.concepte : `${item.compte} · ${item.tipus || item.categoria}` }}
                </span>
              </span>
              <span class="rail-side">
                <span class="mono" :class="{ 'is-in': item.import_value > 0 }">{{ signed(item.import_value) }}</span>
                <span class="subtle">{{ formatDate(item.data) }}</span>
              </span>
            </button>
          </li>
        </ul>
      </aside>

      <div class="col-handle col-handle-rail" role="separator" aria-orientation="vertical" aria-label="Amplada de la llista" @pointerdown="startResize($event, 'rail')" />

      <!-- ── The movement, what it paid, and its lines ─────────────────── -->
      <section v-if="current" class="invoice card" aria-label="Moviment">
        <article class="inv">
          <div class="inv-top">
            <span class="eyebrow">
              {{ current.compte || 'Extracte' }}<template v-if="current.codi"> · {{ current.codi }}</template>
            </span>
            <span class="inv-nav">
              <button type="button" class="btn btn-ghost btn-icon btn-sm" :disabled="!prevRef" title="Anterior (K)" @click="open(prevRef)">
                <AppIcon name="chevron" :size="14" class="flip" />
              </button>
              <span class="subtle mono">{{ position + 1 }}/{{ frozen.length }}</span>
              <button type="button" class="btn btn-ghost btn-icon btn-sm" :disabled="!nextRef" title="Següent (J)" @click="open(nextRef)">
                <AppIcon name="chevron" :size="14" />
              </button>
            </span>
          </div>
          <h2 class="inv-supplier">{{ current.concepte || 'Sense concepte' }}</h2>
          <span v-if="current.mes_dades" class="subtle inv-cif">{{ current.mes_dades }}</span>

          <div class="inv-amount">
            <span class="amount mono" :class="{ 'is-in': current.import_value > 0 }">{{ signed(current.import_value) }}</span>
            <span class="inv-date">
              {{ formatDate(current.data) || 'Sense data' }}
              <span v-if="current.curs" class="badge badge-neutral mono" title="Curs escolar del moviment">{{ current.curs }}</span>
            </span>
          </div>

          <dl class="inv-facts">
            <div>
              <dt>Tipus</dt>
              <dd>{{ current.tipus || '—' }}</dd>
            </div>
            <div>
              <dt>Partides</dt>
              <dd>{{ current.sentit === 'ingres' ? "D'ingressos" : 'De despeses' }}</dd>
            </div>
          </dl>

          <div class="paid">
            <span class="desc-label"><AppIcon name="invoice" :size="12" /> {{ current.factures.length > 1 ? `Paga ${current.factures.length} factures` : current.factures.length ? 'Paga la factura' : 'Factura' }}</span>
            <div v-for="invoice in current.factures" :key="invoice.reference" class="paid-invoice">
              <div class="paid-head">
                <span class="paid-supplier truncate">{{ invoice.proveidor || 'Sense proveïdor' }}</span>
                <span class="mono">{{ formatAmount(invoice.import_value) }}</span>
              </div>
              <span class="subtle paid-sub">
                {{ invoice.tipus_document || 'Document' }}<template v-if="invoice.num_factura"> · {{ invoice.num_factura }}</template>
                <template v-if="invoice.data_factura"> · {{ formatDate(invoice.data_factura) }}</template>
                <template v-if="invoice.responsable_nom"> · {{ invoice.responsable_nom }}</template>
              </span>
              <div class="desc">
                <span class="desc-label"><AppIcon name="user" :size="12" /> Què s'ha comprat, segons qui ho va comprar</span>
                <p :class="{ muted: !invoice.descripcio_compra }">{{ invoice.descripcio_compra || 'Sense descripció del professorat.' }}</p>
              </div>
              <div class="desc desc-ai">
                <span class="desc-label"><AppIcon name="sparkles" :size="12" class="ai-mark" /> Segons la IA, del document</span>
                <p :class="{ muted: !invoice.descripcio }">{{ invoice.descripcio || 'La IA no n\'ha extret cap descripció.' }}</p>
              </div>
              <div class="inv-actions">
                <button type="button" class="btn btn-outline btn-sm" :disabled="!invoice.file_url" @click="togglePeek(invoice)">
                  <AppIcon name="eye" :size="14" />
                  {{ peekRef === invoice.reference ? "Amaga l'original" : "Veure l'original" }}
                </button>
                <RouterLink class="btn btn-ghost btn-sm" :to="{ name: 'document', params: { internalDocNumber: invoice.reference } }">
                  <AppIcon name="external" :size="14" />
                  Fitxa
                </RouterLink>
              </div>
            </div>
            <p v-if="!current.factures.length" class="paid-none">
              <template v-if="current.categoria === 'pagament'">{{ JUSTIFICACIO[current.match_status] ?? 'Sense factura confirmada.' }}</template>
              <template v-else>Aquest moviment no va amb factura: el concepte és el que diu la partida.</template>
              <RouterLink
                v-if="current.categoria === 'pagament'"
                :to="{ name: 'reconcile', query: { extracte: String(current.import_id), moviment: String(current.id) } }"
              > Justifica'l</RouterLink>
            </p>
          </div>
        </article>

        <article class="charge" :class="{ 'is-dirty': dirty }">
          <SplitEditor
            v-if="draft.length"
            v-model="draft"
            :lines="splitLines"
            :total="total"
            @remove="toggle"
          />
          <p v-else class="chosen-empty">Tria una o més partides al mapa de la dreta.</p>

          <p v-if="saveError" class="notice notice-error"><AppIcon name="alert" :size="14" /><span>{{ saveError }}</span></p>
          <p v-if="askError" class="notice notice-error"><AppIcon name="alert" :size="14" /><span>{{ askError }}</span></p>

          <footer class="charge-actions">
            <button
              type="button"
              class="btn btn-primary"
              :disabled="saving || !splitBalanced || !dirty"
              :title="splitBalanced ? 'Desa i ves al següent (⌘↵)' : 'El repartiment no quadra amb el moviment'"
              @click="save(true)"
            >
              <AppIcon name="check" :size="14" />
              {{ saving ? 'Desant…' : !draft.length && current.estat === 'assignada' ? 'Treu les partides' : 'Desa i següent' }}
              <kbd class="kbd kbd-on">⌘↵</kbd>
            </button>
            <button type="button" class="btn btn-ghost" :disabled="!nextRef" @click="open(nextRef)">Salta</button>
            <span class="charge-state">
              <span v-if="current.estat === 'assignada' && !dirty" class="badge badge-olive"><AppIcon name="check" :size="11" /> Desat</span>
              <span v-else-if="proposalAsIs" class="badge badge-ai" title="Encara no s'ha desat: ⌘↵ la confirma">
                <AppIcon name="sparkles" :size="11" /> Jev
              </span>
              <span v-else-if="dirty" class="badge badge-accent">Sense desar</span>
            </span>
          </footer>
        </article>
      </section>
      <section v-else class="invoice invoice-empty card">
        <p class="empty">{{ queueQuery.isLoading.value ? 'Carregant…' : 'Tria un moviment de la llista.' }}</p>
      </section>

      <div class="col-handle" role="separator" aria-orientation="vertical" aria-label="Amplada de la columna central" @pointerdown="startResize($event, 'middle')" />

      <!-- ── The budget map ────────────────────────────────────────────── -->
      <section class="assign-map card" aria-label="Pressupost">
        <PartidaPicker
          v-if="lines.length"
          ref="picker"
          :partides="lines"
          :selected="draft.map((line) => line.id)"
          :suggested="suggestedMap"
          :movement-year="current?.curs ?? ''"
          :side="current?.sentit ?? 'despesa'"
          :order="order"
          reorderable
          :disabled="!current"
          @toggle="toggle"
          @reorder="reorder"
        >
        </PartidaPicker>
        <p v-else class="empty">{{ budgetQuery.isLoading.value ? 'Carregant el pressupost…' : 'Sense pressupost.' }}</p>
      </section>
    </div>

    <footer class="keys" aria-label="Dreceres">
      <AppIcon name="keyboard" :size="13" />
      <span><kbd class="kbd">J</kbd><kbd class="kbd">K</kbd> moviment</span>
      <span><kbd class="kbd">/</kbd> cerca partida · <kbd class="kbd">↑</kbd><kbd class="kbd">↓</kbd><kbd class="kbd">↵</kbd> tria</span>
      <span><kbd class="kbd">1</kbd><kbd class="kbd">2</kbd><kbd class="kbd">3</kbd> proposta de Jev</span>
      <span><kbd class="kbd">⌘↵</kbd> desa i següent</span>
      <span><kbd class="kbd">O</kbd> original</span>
      <span v-if="jevOn"><kbd class="kbd">P</kbd> pregunta a Jev</span>
    </footer>

    <DocumentPeek
      v-if="peekInvoice"
      :src="peekFile?.url ?? null"
      :type="peekFile?.type ?? ''"
      :loading="originals.get(peekInvoice.reference) === 'loading'"
      :title="peekInvoice.num_factura || 'Sense número'"
      :subtitle="`${peekInvoice.proveidor} · ${formatDate(peekInvoice.data_factura)} · ${formatAmount(peekInvoice.import_value)}`"
      :home="peekHome"
      @close="peekRef = null"
    />
  </div>
</template>

<style scoped>
.partides {
  display: flex;
  flex-direction: column;
  gap: 12px;
  /* The shell's content padding, top and bottom: the map scrolls, not the page. */
  height: calc(100dvh - 60px);
  min-height: 560px;
}

.accounts {
  display: flex;
  gap: 6px;
  min-width: 0;
  margin-top: -4px;
  overflow-x: auto;
  scrollbar-width: none;
}

.accounts .chip {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 3px 10px;
  border: 1px solid var(--line);
  border-radius: var(--r-full);
  background: var(--surface-0);
  color: var(--ink-700);
  font: inherit;
  font-size: var(--text-sm);
  white-space: nowrap;
  cursor: pointer;
}

.accounts .chip span {
  color: var(--ink-400);
  font-variant-numeric: tabular-nums;
}

.accounts .chip.on {
  border-color: var(--accent-500);
  color: var(--accent-700);
}

.accounts .chip:disabled {
  opacity: 0.45;
  cursor: default;
}

.pending-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--accent-600);
}

.head-side {
  display: flex;
  align-items: center;
  gap: 14px;
}

.progress-block {
  display: grid;
  gap: 4px;
  min-width: 140px;
}

.progress-label {
  font-size: var(--text-sm);
}

.progress-block .progress > span {
  background: var(--olive-700);
}

.work {
  display: grid;
  flex: 1;
  grid-template-columns: var(--rail-w, 220px) 12px var(--middle-w, 360px) 12px minmax(420px, 1fr);
  min-height: 0;
}

/* Where two columns part: drag to give one more room. */
.col-handle {
  position: relative;
  cursor: col-resize;
  touch-action: none;
}

.col-handle::before {
  content: '';
  position: absolute;
  top: 0;
  bottom: 0;
  left: 5px;
  width: 2px;
  border-radius: 1px;
  background: transparent;
  transition: background 0.1s;
}

.col-handle:hover::before,
.col-handle:active::before {
  background: var(--accent-300);
}

/* ── Rail ─────────────────────────────────────────────────────────────── */
/* Three panels side by side, each as tall as the work area and never wider
   than its column, whatever a long name or a big count inside would like. */
.work > * {
  min-width: 0;
}

.rail {
  display: grid;
  grid-template-columns: minmax(0, 1fr);
  grid-template-rows: auto auto minmax(0, 1fr);
  gap: 6px;
  min-height: 0;
  padding: 8px 6px 4px;
}

.rail-tabs {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 2px;
  padding: 2px;
  border: 1px solid var(--line);
  border-radius: var(--r-md);
  background: var(--surface-2);
}

.rail-tab {
  display: flex;
  flex-direction: column;
  align-items: center;
  min-width: 0;
  padding: 3px 2px;
  line-height: 1.25;
  border: 0;
  border-radius: var(--r-sm);
  background: none;
  color: var(--ink-500);
  font: inherit;
  font-size: var(--text-xs);
  font-weight: 600;
  cursor: pointer;
}

.rail-tab.on {
  background: var(--surface-0);
  color: var(--ink-900);
  box-shadow: var(--shadow-xs);
}

.rail-count {
  color: var(--ink-400);
  font-size: 10px;
  font-weight: 500;
  font-variant-numeric: tabular-nums;
}

.rail-search {
  height: 30px;
}

.rail-list {
  min-height: 0;
  margin: 0;
  padding: 0;
  overflow-y: auto;
  list-style: none;
}

.rail-empty {
  padding: 16px 8px;
  color: var(--ink-400);
  font-size: var(--text-sm);
}

.rail-item {
  display: grid;
  grid-template-columns: 14px minmax(0, 1fr) auto;
  align-items: center;
  gap: 8px;
  width: 100%;
  padding: 6px 8px;
  border: 1px solid transparent;
  border-radius: var(--r-md);
  background: none;
  color: var(--ink-900);
  font: inherit;
  text-align: left;
  cursor: pointer;
}

.rail-item:hover {
  background: var(--surface-2);
}

.rail-item.on {
  border-color: var(--accent-300);
  background: var(--accent-50);
}

.state {
  display: grid;
  place-items: center;
  width: 14px;
  height: 14px;
  border-radius: var(--r-full);
}

.state-pendent {
  border: 1.5px solid var(--gold-500);
  color: var(--gold-800);
}

.state-proposta {
  background: var(--ai-100);
  color: var(--ai-600);
}

.state-assignada {
  background: var(--olive-700);
  color: #fff;
}

.rail-main {
  display: grid;
  min-width: 0;
  line-height: 1.3;
}

.rail-name {
  font-size: var(--text-sm);
  font-weight: 600;
}

.rail-sub {
  color: var(--ink-400);
  font-size: var(--text-xs);
}

.rail-side {
  display: grid;
  justify-items: end;
  font-size: var(--text-xs);
  line-height: 1.35;
}

/* ── The invoice ──────────────────────────────────────────────────────── */
/* One panel: the movement scrolls, what it is charged to stays at the foot. */
.invoice {
  display: flex;
  flex-direction: column;
  min-height: 0;
  overflow: hidden;
}

.invoice-empty {
  align-items: center;
  justify-content: center;
}

.inv {
  display: grid;
  flex: 1;
  align-content: start;
  gap: 4px;
  min-height: 0;
  overflow-y: auto;
  padding: 14px 16px;
}

.inv-top {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.inv-nav {
  display: inline-flex;
  align-items: center;
  gap: 2px;
  font-size: var(--text-xs);
}

.flip {
  transform: rotate(180deg);
}

.inv-supplier {
  margin: 0;
  color: var(--ink-900);
  font-size: var(--text-lg);
  font-weight: 650;
  line-height: 1.25;
}

.inv-cif {
  font-size: var(--text-sm);
}

.inv-amount {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 8px;
  margin: 8px 0 4px;
  padding: 10px 12px;
  border-radius: var(--r-md);
  background: var(--surface-1);
}

.amount {
  color: var(--ink-900);
  font-size: var(--text-xl);
  font-weight: 650;
}

.inv-date {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  color: var(--ink-500);
  font-size: var(--text-sm);
}

.inv-facts {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 8px 12px;
  margin: 6px 0;
}

.inv-facts dt {
  color: var(--ink-400);
  font-size: var(--text-xs);
  font-weight: 600;
  letter-spacing: 0.03em;
  text-transform: uppercase;
}

.inv-facts dd {
  margin: 1px 0 0;
  font-size: var(--text-base);
}

.desc {
  display: grid;
  gap: 3px;
  margin-top: 6px;
  padding: 8px 10px;
  border-left: 3px solid var(--line-strong);
  border-radius: 0 var(--r-md) var(--r-md) 0;
  background: var(--surface-1);
}

.desc-ai {
  border-left-color: var(--ai-400);
  background: var(--ai-50);
}

.desc-label {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  color: var(--ink-400);
  font-size: var(--text-xs);
  font-weight: 600;
}

.desc p {
  margin: 0;
  font-size: var(--text-base);
  line-height: 1.45;
  white-space: pre-line;
}

.inv-actions {
  display: flex;
  gap: 6px;
  margin-top: 8px;
}

.is-in {
  color: var(--olive-700);
}

.paid {
  display: grid;
  gap: 8px;
  margin-top: 8px;
  padding-top: 10px;
  border-top: 1px solid var(--line);
}

.paid-invoice {
  display: grid;
  gap: 2px;
}

.paid-invoice + .paid-invoice {
  padding-top: 8px;
  border-top: 1px dashed var(--line);
}

.paid-head {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 8px;
}

.paid-supplier {
  font-size: var(--text-base);
  font-weight: 600;
}

.paid-sub {
  font-size: var(--text-xs);
}

.paid-none {
  margin: 0;
  padding: 10px;
  border: 1px dashed var(--line-strong);
  border-radius: var(--r-md);
  color: var(--ink-500);
  font-size: var(--text-sm);
}

/* ── What it is charged to ────────────────────────────────────────────── */
.charge {
  display: grid;
  gap: 10px;
  padding: 12px 14px;
}

.charge {
  flex: none;
  max-height: 60%;
  overflow-y: auto;
  border-top: 1px solid var(--line);
  background: var(--surface-1);
}

.charge.is-dirty {
  border-top-color: var(--accent-300);
  background: var(--accent-50);
}

.chosen-empty {
  margin: 0;
  padding: 14px;
  border: 1px dashed var(--line-strong);
  border-radius: var(--r-md);
  color: var(--ink-400);
  font-size: var(--text-sm);
  text-align: center;
}

.charge-actions {
  display: flex;
  align-items: center;
  gap: 6px;
}

.charge-state {
  display: inline-flex;
  min-width: 0;
}

.charge-actions .btn-primary {
  flex: 1;
  justify-content: center;
}

.kbd {
  display: inline-block;
  min-width: 16px;
  padding: 0 4px;
  border: 1px solid var(--line-strong);
  border-radius: var(--r-xs);
  background: var(--surface-0);
  color: var(--ink-500);
  font-family: var(--font-mono);
  font-size: 10px;
  line-height: 15px;
  text-align: center;
}

.kbd-on {
  margin-left: 4px;
  border-color: rgba(255, 255, 255, 0.35);
  background: rgba(255, 255, 255, 0.12);
  color: #fff;
}

/* ── Map ──────────────────────────────────────────────────────────────── */
.assign-map {
  display: grid;
  min-height: 0;
  padding: 12px;
  background: var(--surface-1);
}

.keys {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 4px 16px;
  color: var(--ink-400);
  font-size: var(--text-xs);
}

.keys .kbd + .kbd {
  margin-left: 2px;
}

@media (max-width: 1280px) {
  .work {
    grid-template-columns: var(--middle-w, 360px) 12px minmax(0, 1fr);
  }

  .rail,
  .col-handle-rail {
    display: none;
  }
}

@media (max-width: 900px) {
  .partides {
    height: auto;
  }

  .work {
    grid-template-columns: minmax(0, 1fr);
    gap: 12px;
  }

  .col-handle {
    display: none;
  }

  .assign-map {
    min-height: 70vh;
  }

  .keys {
    display: none;
  }
}
</style>
