<script lang="ts">
import type { SferaDashboard } from '../../sfera/dashboard'
// The last read survives leaving the screen, for this window only: coming back
// shows it at once, dated, instead of an empty page. Nothing is written to disk or the hub.
const memory: { data: SferaDashboard | null; budgetId: number | undefined } = { data: null, budgetId: undefined }
</script>

<script setup lang="ts">
/**
 * Esfer@ · Tauler: the centre's money at a glance — treasury, budget execution,
 * earmarked funds, what is pending — read live from the portal session that
 * Cosecre keeps hidden behind the screen.
 */
import { keepsPortal } from './portal-routes'
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { onBeforeRouteLeave } from 'vue-router'
import AppIcon from '../../components/AppIcon.vue'
import type { IconName } from '../../components/icons'
import { usePlatform } from '../../platform'
import type { SferaCentreOption } from '../../sfera/dashboard'
import BalanceChart from './dashboard/BalanceChart.vue'
import ExecMeter from './dashboard/ExecMeter.vue'
import FlowChart from './dashboard/FlowChart.vue'
import FundsTable from './dashboard/FundsTable.vue'
import LinesTable from './dashboard/LinesTable.vue'
import RecordsPanel from './dashboard/RecordsPanel.vue'
import { clock, dayLabel, dayShort, euro, euro0, pct, pctLabel, seconds } from './dashboard/format'

const platform = usePlatform()
const data = ref<SferaDashboard | null>(memory.data)
const budgetId = ref<number | undefined>(memory.budgetId)
const busy = ref(false)
const phase = ref<'portal' | 'reading' | null>(null)
const error = ref('')
const centres = ref<SferaCentreOption[]>([])
const elapsed = ref(0)
type Tab = 'resum' | 'partides' | 'fons' | 'registres'
const tab = ref<Tab>('resum')
const linesKind = ref<'I' | 'D'>('D')
const fundFilter = ref<string | null>(null)
const party = ref<string | null>(null)
const recordSet = ref<'invoices' | 'incomes'>('invoices')
let alive = true, preservePortal = false, portalReady = false, timer: ReturnType<typeof setInterval> | undefined

// ── Derived views ──────────────────────────────────────────────────────────
const exec = computed(() => data.value?.execution)
const banks = computed(() => data.value?.treasury.accounts.filter(a => a.kind === 'bank') ?? [])
const boxes = computed(() => data.value?.treasury.accounts.filter(a => a.kind === 'cash' && (a.active || Math.abs(a.balance) > 0.004)) ?? [])
const yearTotals = computed(() => (data.value?.months ?? []).reduce((s, m) => ({ in: s.in + m.collected, out: s.out + m.paid }), { in: 0, out: 0 }))
const years = computed(() => [...new Set((data.value?.budgets ?? []).map(b => b.year))])
const budgetsOfYear = computed(() => (data.value?.budgets ?? []).filter(b => b.year === data.value?.budget.year))
const topSpend = computed(() => (data.value?.lines ?? []).filter(l => l.kind === 'D' && !l.parent && l.imputed > 0.004).sort((a, b) => b.imputed - a.imputed).slice(0, 7))
const ranking = (rows: { party: string; total: number; cancelled: boolean }[]) => {
  const map = new Map<string, { name: string; total: number; count: number }>()
  for (const r of rows) {
    if (r.cancelled || !r.party) continue
    const e = map.get(r.party) ?? { name: r.party, total: 0, count: 0 }
    e.total += r.total; e.count++; map.set(r.party, e)
  }
  return [...map.values()].sort((a, b) => b.total - a.total)
}
const suppliers = computed(() => ranking((data.value?.invoices ?? []).map(r => ({ party: r.supplier, total: r.total, cancelled: r.cancelled }))))
const contributors = computed(() => ranking((data.value?.incomes ?? []).map(r => ({ party: r.contributor, total: r.total, cancelled: r.cancelled }))))
const rankMax = (list: { total: number }[]) => Math.max(1, ...list.slice(0, 7).map(s => s.total))

type Alert = { tone: 'danger' | 'warn' | 'info'; icon: IconName; title: string; detail: string; action?: () => void; actionLabel?: string }
const alerts = computed<Alert[]>(() => {
  const d = data.value
  if (!d) return []
  const list: Alert[] = []
  const over = d.lines.filter(l => l.kind === 'D' && l.available < -0.004)
  if (over.length) list.push({ tone: 'danger', icon: 'alert', title: `${over.length} ${over.length === 1 ? 'partida' : 'partides'} de despesa amb excés`, detail: `S’ha executat ${euro(-over.reduce((s, l) => s + l.available, 0))} per sobre del pressupostat.`, action: () => openLines('D', null, true), actionLabel: 'Revisar' })
  const negative = d.treasury.accounts.filter(a => a.balance < -0.004)
  if (negative.length) list.push({ tone: 'danger', icon: 'bank', title: `Saldo negatiu a ${negative.map(a => a.name).join(', ')}`, detail: euro(negative.reduce((s, a) => s + a.balance, 0)) })
  if (Math.abs(d.execution.balance) > 0.004) list.push({ tone: 'warn', icon: 'alert', title: 'Pressupost desequilibrat', detail: `Ingressos i despeses pressupostats difereixen en ${euro(d.execution.balance)}.` })
  const unpaid = d.invoices.filter(r => !r.cancelled && r.pending > 0.004)
  if (unpaid.length) list.push({ tone: 'warn', icon: 'invoice', title: `${unpaid.length} ${unpaid.length === 1 ? 'factura pendent' : 'factures pendents'} de pagament`, detail: euro(unpaid.reduce((s, r) => s + r.pending, 0)), action: () => openRecords('invoices'), actionLabel: 'Veure' })
  if (d.eInvoicesPending) list.push({ tone: 'warn', icon: 'inbox', title: `${d.eInvoicesPending} ${d.eInvoicesPending === 1 ? 'factura electrònica' : 'factures electròniques'} per registrar`, detail: 'Pendents a la safata de factura electrònica d’Esfer@.' })
  const uncollected = d.incomes.filter(r => !r.cancelled && r.pending > 0.004)
  if (uncollected.length) list.push({ tone: 'info', icon: 'clock', title: `${uncollected.length} ${uncollected.length === 1 ? 'ingrés pendent' : 'ingressos pendents'} de cobrament`, detail: euro(uncollected.reduce((s, r) => s + r.pending, 0)), action: () => openRecords('incomes'), actionLabel: 'Veure' })
  if (d.budget.state !== 'A' && d.budget.state !== 'T') list.push({ tone: 'info', icon: 'info', title: `Pressupost ${d.budget.stateLabel.toLowerCase()}`, detail: 'Encara no està aprovat a Esfer@.' })
  return list
})

function openLines(kind: 'I' | 'D', fund: string | null, overOnly = false) {
  linesKind.value = kind; fundFilter.value = fund; tab.value = 'partides'
  if (overOnly) fundFilter.value = null
}
function openRecords(set: 'invoices' | 'incomes', who: string | null = null) { recordSet.value = set; party.value = who; tab.value = 'registres' }
const topShare = computed(() => pct(topSpend.value.reduce((s, l) => s + l.imputed, 0), exec.value?.expense.imputed ?? 0))

// ── Reading ────────────────────────────────────────────────────────────────
async function waitForPortal(id: string) {
  // Auto-login and the portal's own boot take a few seconds after the view opens.
  const end = Date.now() + 45000
  while (alive && Date.now() < end) {
    const state = await platform.browser!.state(id)
    if (state.login === 'manual' && /autenticaciogicar/.test(state.url)) throw new Error('Esfer@ demana identificació. Obre el navegador i identifica’t, o desa el teu accés a «El meu accés».')
    if (state.login === 'error') throw new Error(state.loginMessage ?? 'No s’ha pogut iniciar la sessió a GICAR. Obre el navegador.')
    if (!state.loading && /\/bfgh\/gestioeconomica\//.test(state.url)) return
    await new Promise(done => setTimeout(done, 600))
  }
  throw new Error('Esfer@ triga a obrir-se. Obre el navegador per veure què passa.')
}

async function load(nextBudget?: number, centre?: string) {
  if (!platform.sferaDashboard || !platform.browser || busy.value) return
  busy.value = true; error.value = ''; elapsed.value = 0
  const started = performance.now()
  timer = setInterval(() => { elapsed.value = Math.round(performance.now() - started) }, 100)
  try {
    if (!portalReady) {
      phase.value = 'portal'
      const state = await platform.browser.open('sfera')
      if (!alive) return
      await platform.browser.layout(state.id, null)
      await waitForPortal(state.id)
      portalReady = true
    }
    phase.value = 'reading'
    let result = centre ? await platform.sferaDashboard.selectCentre(centre) : await platform.sferaDashboard.load(nextBudget ? { budgetId: nextBudget } : {})
    // The portal may still be booting AngularJS right after its page loads.
    // Auto-login can still be landing too: the token appears once GICAR hands back.
    for (let i = 0; !result.ok && !result.centres && /carregant|s’està obrint|Identifica’t/.test(result.error) && i < 8 && alive; i++) {
      await new Promise(done => setTimeout(done, 1500))
      result = await platform.sferaDashboard.load(nextBudget ? { budgetId: nextBudget } : {})
    }
    if (!alive) return
    if (result.ok) {
      data.value = result.data; centres.value = []
      budgetId.value = result.data.budget.id
      memory.data = result.data; memory.budgetId = budgetId.value
    } else {
      error.value = result.error; centres.value = result.centres ?? []
      if (result.centres) { data.value = null; memory.data = null }
    }
  } catch (e) {
    if (alive) error.value = e instanceof Error ? e.message.replace(/^Error invoking remote method '[^']+': (Error: )?/, '') : 'No es pot llegir Esfer@.'
  } finally {
    clearInterval(timer); phase.value = null
    if (alive) busy.value = false
  }
}
function chooseYear(year: number) {
  const list = data.value?.budgets.filter(b => b.year === year) ?? []
  const pick = list.find(b => b.kind === data.value?.budget.kind) ?? list.find(b => b.kind === 'G') ?? list[0]
  if (pick) void load(pick.id)
}

onBeforeRouteLeave(to => { preservePortal = keepsPortal(to.name) })
onMounted(() => { void load(budgetId.value) })
onBeforeUnmount(() => {
  alive = false; clearInterval(timer)
  if (!preservePortal) void platform.browser?.release('sfera').catch(() => {})
})
</script>

<template>
  <div class="dash">
    <header class="head">
      <div class="title">
        <h1 class="page-title">Esfer@ · Tauler econòmic</h1>
        <p class="page-lead">
          <template v-if="data">
            <strong>{{ data.centre.name }}</strong> <span class="mono">{{ data.centre.code }}</span>
            · llegit a les {{ clock(data.completedAt) }} en {{ seconds(data.durationMs) }}
          </template>
          <template v-else>Tresoreria, execució del pressupost i pendents, llegits en directe del portal.</template>
        </p>
      </div>
      <div class="controls">
        <template v-if="data">
          <label class="sel">
            <span class="sr-only">Exercici</span>
            <select class="select" :value="data.budget.year" :disabled="busy" aria-label="Exercici" @change="chooseYear(Number(($event.target as HTMLSelectElement).value))">
              <option v-for="y in years" :key="y" :value="y">{{ y }}</option>
            </select>
          </label>
          <div class="seg" role="radiogroup" aria-label="Pressupost">
            <button v-for="b in budgetsOfYear" :key="b.id" role="radio" type="button" :aria-checked="b.id === data.budget.id" :class="{ on: b.id === data.budget.id }" :disabled="busy" @click="load(b.id)">{{ b.kindLabel }}</button>
          </div>
        </template>
        <button class="btn btn-outline" type="button" :disabled="busy" @click="load(budgetId)">
          <AppIcon name="refresh" :class="{ spin: busy }" />{{ busy ? (phase === 'portal' ? 'Obrint Esfer@…' : `Llegint… ${seconds(elapsed)}`) : 'Actualitzar' }}
        </button>
        <RouterLink class="btn btn-ghost" :to="{ name: 'sfera' }"><AppIcon name="monitor" />Navegador</RouterLink>
      </div>
    </header>

    <div v-if="error && !centres.length" class="notice notice-error" role="alert">
      <AppIcon name="alert" />
      <span>{{ error }}<template v-if="data"> Es mostra la lectura anterior, de les {{ clock(data.completedAt) }}.</template></span>
    </div>

    <!-- Esfer@ is waiting for a centre: offer its own list here. -->
    <section v-if="centres.length" class="card picker">
      <div class="card-head"><div><h2 class="card-title">Tria el centre</h2><p class="muted">Esfer@ ha obert la sessió i espera que triïs amb quin centre treballes.</p></div></div>
      <div class="centres">
        <button v-for="c in centres" :key="c.code" class="centre" type="button" :disabled="busy" @click="load(undefined, c.code)">
          <AppIcon name="home" /><span><strong>{{ c.name }}</strong><span class="mono">{{ c.code }}</span></span>
        </button>
      </div>
    </section>

    <!-- First read: a quiet skeleton, sized like what is coming. -->
    <section v-else-if="!data && busy" class="loading" aria-busy="true" aria-live="polite">
      <div class="kpis skeleton"><div v-for="i in 5" :key="i" class="kpi"><span class="bar s" /><span class="bar l" /><span class="bar m" /></div></div>
      <p class="muted">{{ phase === 'portal' ? 'Obrint la sessió d’Esfer@ (identificació automàtica)…' : 'Llegint pressupost, tresoreria, factures, ingressos i llibre diari…' }} {{ seconds(elapsed) }}</p>
    </section>

    <section v-else-if="!data && !busy && !error" class="card empty"><p>Encara no hi ha dades.</p><button class="btn btn-primary" type="button" @click="load()">Llegir Esfer@</button></section>

    <template v-if="data">
      <!-- KPIs -->
      <section class="card kpis" aria-label="Indicadors principals" :class="{ stale: busy }">
        <div class="kpi lead">
          <span class="label"><AppIcon name="bank" :size="14" />Tresoreria</span>
          <strong class="hero">{{ euro0(data.treasury.total) }}</strong>
          <span class="sub">{{ banks.length }} {{ banks.length === 1 ? 'compte' : 'comptes' }} · {{ boxes.length }} {{ boxes.length === 1 ? 'caixa' : 'caixes' }} · saldo actual</span>
        </div>
        <div class="kpi">
          <span class="label">Ingressos reconeguts</span>
          <strong>{{ euro0(exec!.income.imputed) }}</strong>
          <ExecMeter :value="exec!.income.imputed" :total="exec!.income.budgeted" kind="I" />
          <span class="sub">de {{ euro0(exec!.income.budgeted) }} previstos</span>
        </div>
        <div class="kpi">
          <span class="label">Despesa executada</span>
          <strong>{{ euro0(exec!.expense.imputed) }}</strong>
          <ExecMeter :value="exec!.expense.imputed" :total="exec!.expense.budgeted" kind="D" />
          <span class="sub">de {{ euro0(exec!.expense.budgeted) }} pressupostats</span>
        </div>
        <div class="kpi">
          <span class="label">Disponible per gastar</span>
          <strong :class="{ neg: exec!.expense.available < 0 }">{{ euro0(exec!.expense.available) }}</strong>
          <span class="sub">{{ pctLabel(pct(exec!.expense.available, exec!.expense.budgeted)) }} del pressupost de despesa</span>
          <span class="sub">Romanent anterior {{ euro0(data.budget.remnant) }}</span>
        </div>
        <div class="kpi">
          <span class="label">Cobrat i pagat · {{ data.budget.year }}</span>
          <span class="pair"><i class="in" />Cobraments <b>{{ euro0(exec!.collections.total) }}</b></span>
          <span class="pair"><i class="out" />Pagaments <b>{{ euro0(exec!.payments.total) }}</b></span>
          <span class="sub">Del pressupost {{ data.budget.kindLabel.toLowerCase() }}</span>
        </div>
      </section>

      <nav class="tabs" role="tablist" aria-label="Seccions del tauler">
        <button role="tab" type="button" :aria-selected="tab === 'resum'" :class="{ on: tab === 'resum' }" @click="tab = 'resum'"><AppIcon name="chart" :size="14" />Resum</button>
        <button role="tab" type="button" :aria-selected="tab === 'partides'" :class="{ on: tab === 'partides' }" @click="tab = 'partides'; fundFilter = null"><AppIcon name="layers" :size="14" />Partides</button>
        <button role="tab" type="button" :aria-selected="tab === 'fons'" :class="{ on: tab === 'fons' }" @click="tab = 'fons'"><AppIcon name="tag" :size="14" />Fons finalistes</button>
        <button role="tab" type="button" :aria-selected="tab === 'registres'" :class="{ on: tab === 'registres' }" @click="tab = 'registres'"><AppIcon name="invoice" :size="14" />Factures i ingressos</button>
        <span class="budget-meta">
          Pressupost {{ data.budget.year }} {{ data.budget.kindLabel.toLowerCase() }} ·
          <span class="badge" :class="data.budget.state === 'A' ? 'badge-olive' : data.budget.state === 'T' ? 'badge-neutral' : 'badge-gold'">{{ data.budget.stateLabel }}</span>
          <template v-if="data.budget.approvedAt"> · aprovat el {{ dayLabel(data.budget.approvedAt) }}</template>
        </span>
      </nav>

      <!-- Resum -->
      <div v-if="tab === 'resum'" class="grid" :class="{ stale: busy }">
        <div class="col">
          <section class="card span-2">
            <div class="card-head">
              <div><h2 class="card-title">Saldo de tresoreria</h2><p class="muted">Bancs i caixes del centre, dia a dia{{ data.treasury.seriesYear ? ` durant ${data.treasury.seriesYear}` : '' }}.</p></div>
            </div>
            <div class="card-body">
              <BalanceChart v-if="data.treasury.seriesYear && data.treasury.series.length > 1" :series="data.treasury.series" :year="data.treasury.seriesYear" />
              <p v-else class="muted">L’evolució del saldo es reconstrueix a partir del saldo actual i només es mostra per a l’exercici més recent.</p>
            </div>
          </section>
          <section class="card span-2">
            <div class="card-head">
              <div><h2 class="card-title">Cobraments i pagaments per mes</h2><p class="muted">Diners que entren i surten de bancs i caixes el {{ data.budget.year }}; els traspassos entre comptes del centre no compten.</p></div>
              <div class="totals"><span>Cobrat <b>{{ euro0(yearTotals.in) }}</b></span><span>Pagat <b>{{ euro0(yearTotals.out) }}</b></span></div>
            </div>
            <div class="card-body"><FlowChart :months="data.months" /></div>
          </section>
          <section class="card span-2">
            <div class="card-head">
              <div><h2 class="card-title">Partides de despesa amb més execució</h2><p class="muted">Executat sobre el pressupostat de cada partida.</p></div>
              <button class="btn btn-ghost btn-sm" type="button" @click="openLines('D', null)">Totes les partides</button>
            </div>
            <table class="table compact">
              <tbody>
                <tr v-for="l in topSpend" :key="l.code" :class="{ over: l.available < -0.004 }">
                  <td class="name"><span>{{ l.name }}</span><small class="mono">{{ l.code.replace(/^D\//, '') }}</small></td>
                  <td class="num">{{ euro(l.imputed) }}<small> de {{ euro0(l.budgeted) }}</small></td>
                  <td class="meter-col"><ExecMeter :value="l.imputed" :total="l.budgeted" kind="D" /></td>
                </tr>
                <tr v-if="!topSpend.length"><td class="muted">Encara no hi ha despesa executada.</td></tr>
              </tbody>
            </table>
            <p v-if="topSpend.length" class="foot muted">{{ pctLabel(topShare) }} de la despesa executada és en aquestes {{ topSpend.length }} partides.</p>
          </section>
          <section class="card span-2">
            <div class="card-head"><div><h2 class="card-title">Darrers moviments de tresoreria</h2><p class="muted">Del llibre diari d’operacions, en bancs i caixes.</p></div></div>
            <div class="table-scroll moves">
              <table class="table compact">
                <thead><tr><th scope="col">Data</th><th scope="col">Operació</th><th scope="col">Concepte</th><th scope="col">Compte</th><th scope="col" class="num">Import</th></tr></thead>
                <tbody>
                  <tr v-for="(m, i) in data.movements.slice(0, 14)" :key="i">
                    <td class="nowrap">{{ dayShort(m.date) }}</td>
                    <td class="nowrap small">{{ m.typeLabel }}</td>
                    <td class="desc">{{ m.description }}</td>
                    <td class="nowrap small">{{ m.account }}</td>
                    <td class="num amount" :class="m.amount < 0 ? 'out' : 'in'"><AppIcon :name="m.amount < 0 ? 'arrowDown' : 'arrowUp'" :size="12" />{{ euro(Math.abs(m.amount)) }}</td>
                  </tr>
                  <tr v-if="!data.movements.length"><td colspan="5" class="muted">No hi ha moviments de tresoreria aquest exercici.</td></tr>
                </tbody>
              </table>
            </div>
          </section>
        </div>
        <div class="col">
          <section class="card">
            <div class="card-head"><h2 class="card-title">Comptes i caixes</h2><span class="muted num">{{ euro(data.treasury.total) }}</span></div>
            <ul class="accounts">
              <li v-for="a in [...banks, ...boxes]" :key="a.code" :class="{ inactive: !a.active }">
                <AppIcon :name="a.kind === 'bank' ? 'bank' : 'inbox'" :size="15" />
                <span class="acc-name">{{ a.name }}<small>{{ a.kind === 'bank' ? `Banc ${a.detail ?? ''}` : a.detail ?? 'Caixa' }}{{ a.main ? ' · principal' : '' }}{{ a.active ? '' : ' · inactiu' }}</small></span>
                <span class="share"><span :style="{ width: `${Math.max(0, pct(a.balance, data.treasury.total)) * 100}%` }" /></span>
                <strong class="num" :class="{ neg: a.balance < 0 }">{{ euro(a.balance) }}</strong>
              </li>
            </ul>
          </section>
          <section class="card">
            <div class="card-head"><h2 class="card-title">Avisos</h2><span v-if="alerts.length" class="badge badge-neutral">{{ alerts.length }}</span></div>
            <ul v-if="alerts.length" class="alerts">
              <li v-for="(a, i) in alerts" :key="i" :class="a.tone">
                <AppIcon :name="a.icon" :size="15" />
                <span><strong>{{ a.title }}</strong><small>{{ a.detail }}</small></span>
                <button v-if="a.action" class="btn btn-ghost btn-sm" type="button" @click="a.action">{{ a.actionLabel }}</button>
              </li>
            </ul>
            <p v-else class="all-clear"><AppIcon name="check" :size="15" />Cap avís: no hi ha excés de despesa, saldos negatius ni pendents.</p>
          </section>
          <section class="card">
            <div class="card-head"><h2 class="card-title">Proveïdors principals</h2><button class="btn btn-ghost btn-sm" type="button" @click="openRecords('invoices')">Factures</button></div>
            <ol class="rank">
              <li v-for="s in suppliers.slice(0, 7)" :key="s.name">
                <button type="button" class="rank-row" :title="`Veure les factures de ${s.name}`" @click="openRecords('invoices', s.name)">
                  <span class="rank-name">{{ s.name }}<small>{{ s.count }} {{ s.count === 1 ? 'factura' : 'factures' }}</small></span>
                  <span class="rank-bar"><span class="expense" :style="{ width: `${Math.max(0, s.total / rankMax(suppliers)) * 100}%` }" /></span>
                  <strong class="num">{{ euro0(s.total) }}</strong>
                </button>
              </li>
              <li v-if="!suppliers.length" class="muted">Cap factura registrada en aquest pressupost.</li>
            </ol>
          </section>
          <section class="card">
            <div class="card-head"><h2 class="card-title">Aportadors principals</h2><button class="btn btn-ghost btn-sm" type="button" @click="openRecords('incomes')">Ingressos</button></div>
            <ol class="rank">
              <li v-for="s in contributors.slice(0, 7)" :key="s.name">
                <button type="button" class="rank-row" :title="`Veure els ingressos de ${s.name}`" @click="openRecords('incomes', s.name)">
                  <span class="rank-name">{{ s.name }}<small>{{ s.count }} {{ s.count === 1 ? 'ingrés' : 'ingressos' }}</small></span>
                  <span class="rank-bar"><span class="income" :style="{ width: `${Math.max(0, s.total / rankMax(contributors)) * 100}%` }" /></span>
                  <strong class="num">{{ euro0(s.total) }}</strong>
                </button>
              </li>
              <li v-if="!contributors.length" class="muted">Cap ingrés registrat en aquest pressupost.</li>
            </ol>
          </section>
        </div>
      </div>

      <section v-else-if="tab === 'partides'" class="card pane" :class="{ stale: busy }">
        <div class="card-head">
          <div class="seg" role="radiogroup" aria-label="Tipus de partida">
            <button role="radio" type="button" :aria-checked="linesKind === 'D'" :class="{ on: linesKind === 'D' }" @click="linesKind = 'D'">Despeses</button>
            <button role="radio" type="button" :aria-checked="linesKind === 'I'" :class="{ on: linesKind === 'I' }" @click="linesKind = 'I'">Ingressos</button>
          </div>
          <button v-if="fundFilter" class="chip" type="button" @click="fundFilter = null">Fons {{ fundFilter }} <AppIcon name="close" :size="12" /></button>
        </div>
        <div class="card-body"><LinesTable :lines="data.lines" :kind="linesKind" :fund="fundFilter" @fund="code => (fundFilter = code)" /></div>
      </section>

      <section v-else-if="tab === 'fons'" class="card pane" :class="{ stale: busy }">
        <div class="card-head"><div><h2 class="card-title">Fons finalistes</h2></div></div>
        <div class="card-body"><FundsTable :lines="data.lines" @open="code => openLines('D', code)" /></div>
      </section>

      <section v-else class="card pane" :class="{ stale: busy }">
        <div class="card-body"><RecordsPanel :invoices="data.invoices" :incomes="data.incomes" :party="party" :set="recordSet" @party="name => (party = name)" /></div>
      </section>

      <details class="trace">
        <summary>Com s’ha llegit · {{ data.requests.length }} peticions a Esfer@ en {{ seconds(data.durationMs) }}</summary>
        <p class="muted">Només lectures, amb la sessió del navegador d’Esfer@. Les dades es guarden en aquesta finestra mentre és oberta; no es desen al Hub ni al disc. Esfer@ és la referència oficial.</p>
        <table class="table compact">
          <thead><tr><th scope="col">Petició</th><th scope="col">Resposta</th><th scope="col" class="num">Files</th><th scope="col" class="num">Temps</th></tr></thead>
          <tbody><tr v-for="(r, i) in data.requests" :key="i"><td class="mono small">{{ r.method }} {{ r.path.replace('/bfgh/AppJava/bfgh_gesteco/services', '') }}</td><td>{{ r.status ?? '—' }}</td><td class="num">{{ r.rows ?? '—' }}</td><td class="num">{{ seconds(r.durationMs) }}</td></tr></tbody>
        </table>
      </details>
    </template>
  </div>
</template>

<style scoped>
.dash { display: grid; gap: 14px; min-width: 0; }
.head { display: flex; flex-wrap: wrap; align-items: flex-end; justify-content: space-between; gap: 12px 20px; }
.page-lead strong { color: var(--ink-700); font-weight: 600; }
.page-lead .mono { font-size: var(--text-sm); }
.controls { display: flex; flex-wrap: wrap; align-items: center; gap: 8px; }
.controls .select { width: auto; min-width: 84px; }
.seg { display: inline-flex; padding: 2px; border: 1px solid var(--line-strong); border-radius: var(--r-md); background: var(--surface-1); }
.seg button { padding: 4px 10px; border: 0; border-radius: var(--r-sm); background: none; font: inherit; font-size: var(--text-base); color: var(--ink-500); cursor: pointer; }
.seg button.on { background: var(--surface-0); color: var(--ink-900); font-weight: 600; box-shadow: var(--shadow-xs); }
.seg button:disabled { cursor: default; }
.chip { display: inline-flex; align-items: center; gap: 4px; padding: 3px 8px; border: 1px solid var(--accent-300); border-radius: var(--r-sm); background: var(--accent-50); font: inherit; font-size: var(--text-sm); color: var(--accent-700); cursor: pointer; }
.stale { opacity: 0.6; transition: opacity 0.2s; }

/* KPIs: one card, five cells divided by hairlines. */
.kpis { display: grid; grid-template-columns: 1.25fr repeat(4, minmax(0, 1fr)); }
.kpi { display: grid; align-content: start; gap: 6px; padding: 14px 16px; min-width: 0; border-left: 1px solid var(--line); }
.kpi:first-child { border-left: 0; }
.kpi .label { display: flex; align-items: center; gap: 6px; font-size: var(--text-xs); font-weight: 600; letter-spacing: 0.06em; text-transform: uppercase; color: var(--ink-400); }
.kpi strong { font-size: var(--text-2xl); font-weight: 600; color: var(--ink-900); letter-spacing: -0.01em; }
.kpi strong.hero { font-size: 32px; color: var(--accent-700); }
.kpi .sub { font-size: var(--text-sm); color: var(--ink-500); }
.kpi.lead { background: var(--accent-50); border-radius: var(--r-lg) 0 0 var(--r-lg); }
.pair { display: flex; align-items: center; gap: 6px; font-size: var(--text-base); color: var(--ink-500); }
.pair b { margin-left: auto; color: var(--ink-900); font-weight: 600; font-variant-numeric: tabular-nums; }
i.in, i.out { display: inline-block; flex: none; width: 10px; height: 10px; border-radius: 2px; }
i.in { background: #5b8de6; }
i.out { background: #d9774b; }
.neg { color: var(--danger-700) !important; }

.tabs { display: flex; flex-wrap: wrap; align-items: center; gap: 2px; border-bottom: 1px solid var(--line-strong); }
.tabs button { display: inline-flex; align-items: center; gap: 6px; margin-bottom: -1px; padding: 8px 12px; border: 0; border-bottom: 2px solid transparent; background: none; font: inherit; font-size: var(--text-base); color: var(--ink-500); cursor: pointer; }
.tabs button:hover { color: var(--ink-900); }
.tabs button.on { border-bottom-color: var(--accent-600); color: var(--ink-900); font-weight: 600; }
.budget-meta { margin-left: auto; padding: 0 4px 6px; font-size: var(--text-sm); color: var(--ink-500); }

.grid { display: grid; grid-template-columns: minmax(0, 2fr) minmax(300px, 1fr); gap: 14px; align-items: start; }
.col { display: grid; gap: 14px; align-content: start; min-width: 0; }
.card-head .muted { margin-top: 2px; font-size: var(--text-sm); }
.muted { color: var(--ink-400); }
.num { font-variant-numeric: tabular-nums; text-align: right; white-space: nowrap; }
.totals { display: flex; gap: 14px; font-size: var(--text-base); color: var(--ink-500); font-variant-numeric: tabular-nums; }
.totals b { color: var(--ink-900); font-weight: 600; }
.totals span { display: inline-flex; align-items: center; gap: 6px; }

.accounts { margin: 0; padding: 6px 0; list-style: none; }
.accounts li { display: grid; grid-template-columns: 16px minmax(0, 1fr) 44px auto; align-items: center; gap: 10px; padding: 7px 16px; color: var(--ink-500); }
.accounts li + li { border-top: 1px solid var(--line); }
.accounts li.inactive { opacity: 0.6; }
.acc-name { display: grid; min-width: 0; color: var(--ink-900); font-weight: 500; }
.acc-name small, .name small, .rank-name small { overflow: hidden; font-weight: 400; font-size: var(--text-sm); color: var(--ink-400); text-overflow: ellipsis; white-space: nowrap; }
.share { height: 4px; border-radius: var(--r-full); background: var(--surface-3); overflow: hidden; }
.share span { display: block; height: 100%; background: #5b8de6; }
.accounts strong { color: var(--ink-900); font-weight: 600; }

.alerts { margin: 0; padding: 4px 0; list-style: none; }
.alerts li { display: grid; grid-template-columns: 16px minmax(0, 1fr) auto; align-items: start; gap: 10px; padding: 9px 16px; }
.alerts li + li { border-top: 1px solid var(--line); }
.alerts li span { display: grid; gap: 1px; }
.alerts li strong { font-weight: 600; color: var(--ink-900); }
.alerts li small { font-size: var(--text-sm); color: var(--ink-500); }
.alerts li.danger svg { color: var(--danger-600); }
.alerts li.warn svg { color: var(--gold-800); }
.alerts li.info svg { color: var(--accent-600); }
.all-clear { display: flex; align-items: center; gap: 8px; margin: 0; padding: 14px 16px; color: var(--olive-700); font-size: var(--text-base); }

.table.compact td, .table.compact th { padding: 7px 14px; }
.name { display: grid; min-width: 0; }
.name span { color: var(--ink-900); }
.num small { color: var(--ink-400); font-size: var(--text-sm); }
.meter-col { width: 180px; }
tr.over td:first-child { box-shadow: inset 3px 0 0 var(--danger-600); }
.foot { margin: 0; padding: 8px 14px 12px; border-top: 1px solid var(--line); font-size: var(--text-sm); }

.rank { margin: 0; padding: 4px 0; list-style: none; }
.rank > li.muted { padding: 12px 16px; }
.rank-row { display: grid; grid-template-columns: minmax(0, 1fr) 70px auto; align-items: center; gap: 10px; width: 100%; padding: 6px 16px; border: 0; background: none; font: inherit; text-align: left; cursor: pointer; }
.rank-row:hover { background: var(--surface-1); }
.rank-name { display: grid; min-width: 0; color: var(--ink-900); }
.rank-name { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.rank-bar { height: 6px; border-radius: var(--r-full); background: var(--surface-2); overflow: hidden; }
.rank-bar span { display: block; height: 100%; border-radius: inherit; }
.rank-bar .expense { background: #d9774b; }
.rank-bar .income { background: #5b8de6; }
.rank-row strong { font-weight: 600; color: var(--ink-900); }

.moves { max-height: 460px; overflow-y: auto; }
.nowrap { white-space: nowrap; }
.small { font-size: var(--text-sm); color: var(--ink-500); }
.desc { min-width: 220px; color: var(--ink-700); }
.amount { display: table-cell; }
.amount svg { margin-right: 3px; vertical-align: -1px; }
.amount.in { color: var(--ink-900); }
.amount.in svg { color: #3f6fce; }
.amount.out { color: var(--ink-900); }
.amount.out svg { color: #c4643a; }

.pane { min-width: 0; }
.picker .centres { display: grid; grid-template-columns: repeat(auto-fill, minmax(260px, 1fr)); gap: 8px; padding: 14px 16px 16px; }
.centre { display: flex; align-items: center; gap: 10px; padding: 10px 12px; border: 1px solid var(--line-strong); border-radius: var(--r-md); background: var(--surface-0); font: inherit; text-align: left; color: var(--ink-500); cursor: pointer; }
.centre:hover:not(:disabled) { border-color: var(--accent-400); background: var(--accent-50); }
.centre > span { display: grid; }
.centre strong { color: var(--ink-900); font-weight: 600; }
.centre .mono { font-size: var(--text-sm); }

.loading { display: grid; gap: 10px; }
.skeleton .kpi { gap: 10px; }
.bar { display: block; height: 10px; border-radius: var(--r-sm); background: var(--surface-2); animation: pulse 1.4s ease-in-out infinite; }
.bar.s { width: 40%; } .bar.m { width: 60%; } .bar.l { width: 80%; height: 22px; }
@keyframes pulse { 50% { opacity: 0.45; } }

.trace { font-size: var(--text-sm); color: var(--ink-500); }
.trace summary { cursor: pointer; padding: 4px 0; }
.trace p { margin: 6px 0; }
.trace .table { max-width: 720px; background: var(--surface-0); border: 1px solid var(--line); border-radius: var(--r-md); }

@media (max-width: 1180px) {
  .kpis { grid-template-columns: repeat(3, minmax(0, 1fr)); }
  .kpi:nth-child(4) { border-left: 0; }
  .kpi:nth-child(n + 4) { border-top: 1px solid var(--line); }
  .kpi.lead { border-radius: var(--r-lg) 0 0 0; }
  .grid { grid-template-columns: minmax(0, 1fr); }
}
@media (max-width: 720px) {
  .kpis { grid-template-columns: minmax(0, 1fr); }
  .kpi { border-left: 0; border-top: 1px solid var(--line); }
  .kpi:first-child { border-top: 0; }
  .budget-meta { margin-left: 0; }
}
</style>
