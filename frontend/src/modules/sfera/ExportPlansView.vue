<script setup lang="ts">
/**
 * Esfer@ · Plans d'exportació: review what the Hub checked, approve it, and let
 * this desktop write it with the portal session — one item at a time, each
 * result read back. Uncertain writes are settled by reading the portal, never
 * by writing again.
 */
import { keepsPortal } from './portal-routes'
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { onBeforeRouteLeave, useRoute, useRouter } from 'vue-router'
import { usePlatform } from '../../platform'
import type { DiagnosticReport, ExportRunResult } from '../../sfera/export-bridge'
import { STATE_LABELS, type ExportItem, type ExportPlan, type ExportPlanSummary } from '../../sfera/export-contract'
import { exportApi } from './export-api'

const platform = usePlatform()
const route = useRoute()
const router = useRouter()
const plans = ref<ExportPlanSummary[]>([])
const plan = ref<ExportPlan | null>(null)
const busy = ref<string | null>(null)
const error = ref('')
const message = ref('')
const diagnostic = ref<DiagnosticReport | null>(null)
const lastRun = ref<ExportRunResult | null>(null)
let alive = true, preservePortal = false
onBeforeRouteLeave(to => { preservePortal = keepsPortal(to.name) })
onBeforeUnmount(() => { alive = false; if (!preservePortal) void platform.browser?.release('sfera').catch(() => {}) })

const desktop = computed(() => Boolean(platform.sferaExport))
const readable = (e: unknown, fallback: string) => e instanceof Error ? e.message.replace(/^Error invoking remote method '[^']+': (Error|PortalError): /, '') : fallback
const label = (state: string) => STATE_LABELS[state] ?? state
const euro = (value: string | number) => new Intl.NumberFormat('ca-ES', { style: 'currency', currency: 'EUR' }).format(Number(value))
const when = (iso: string) => new Date(iso).toLocaleString('ca-ES', { dateStyle: 'short', timeStyle: 'short' })
const total = computed(() => (plan.value?.items ?? []).reduce((sum, i) => sum + Math.round(Number(i.invoice.total) * 100), 0) / 100)
const deletable = computed(() => Boolean(plan.value?.items.every(i => !i.attempts.length && i.remote_id === null)))
const runnable = (item: ExportItem) => plan.value?.approved_at && ['approved', 'failed'].includes(item.state)
const pending = computed(() => (plan.value?.items ?? []).filter(i => runnable(i)))

async function act<T>(key: string, work: () => Promise<T>, done?: (value: T) => void) {
  if (busy.value) return
  busy.value = key; error.value = ''; message.value = ''
  try { const value = await work(); if (alive) done?.(value) }
  catch (e) { if (alive) error.value = readable(e, 'No s’ha pogut completar l’acció.') }
  finally { if (alive) busy.value = null }
}
async function refreshList() { plans.value = await exportApi.list() }
async function open(id: string) {
  await act('open', () => exportApi.get(id), value => { plan.value = value; lastRun.value = null; void router.replace({ query: { pla: id } }) })
}
async function reload() { if (plan.value) plan.value = await exportApi.get(plan.value.id); await refreshList() }
/** The runner needs the hidden portal view with a session and a centre. */
async function portal() {
  const state = await platform.browser?.open('sfera')
  if (state) await platform.browser?.layout(state.id, null)
}

const approve = () => act('approve', async () => { await exportApi.approve(plan.value!); await reload() }, () => { message.value = 'Pla aprovat. Ja es pot executar.' })
const cancel = () => {
  if (!window.confirm('Cancel·lar els elements pendents? Les factures ja desades a Esfer@ no es desfan.')) return
  void act('cancel', async () => { await exportApi.cancel(plan.value!.id); await reload() })
}
const remove = () => {
  if (!window.confirm('Eliminar aquest pla? Només es pot fer perquè mai no s’ha executat.')) return
  void act('remove', async () => { await exportApi.remove(plan.value!.id); plan.value = null; await refreshList(); void router.replace({ query: {} }) }, () => { message.value = 'Pla eliminat.' })
}
const removeItem = (item: ExportItem) => act(`remove-${item.id}`, async () => { plan.value = await exportApi.removeItem(plan.value!.id, item.id); await refreshList() }, () => { message.value = `${item.source_ref} tret del pla. Revisa’l de nou abans d’aprovar-lo.` })
const recover = (item: ExportItem) => act(`recover-${item.id}`, async () => { plan.value = await exportApi.recover(plan.value!.id, item.id) }, () => { message.value = 'Element marcat com a incert. Concilia’l llegint el portal.' })

async function runOne(item: ExportItem): Promise<ExportRunResult> {
  const result = await platform.sferaExport!.run(plan.value!.id, item.id)
  lastRun.value = result
  await reload()
  return result
}
const run = (item: ExportItem) => act(`run-${item.id}`, async () => { await portal(); return runOne(item) }, result => {
  if (result.outcome === 'succeeded' && !result.error) message.value = `${item.source_ref}: desada a Esfer@ (${result.remoteCode}) i rellegida.`
  else error.value = `${item.source_ref}: ${result.error ?? label(result.outcome)}`
})
/** Executes the pending items in order and stops at the first one that is not a clean success. */
const runAll = () => act('run-all', async () => {
  await portal()
  let saved = 0
  for (const item of [...pending.value]) {
    const result = await runOne(item)
    if (result.outcome !== 'succeeded' || result.error) throw new Error(`${item.source_ref}: ${result.error ?? label(result.outcome)} Aturat; ${saved} desades abans.`)
    saved++
  }
  return saved
}, saved => { message.value = `${saved} factures desades i rellegides a Esfer@.` })
const reconcile = (item: ExportItem) => act(`reconcile-${item.id}`, async () => { await portal(); const r = await platform.sferaExport!.reconcile(plan.value!.id, item.id); lastRun.value = r; await reload(); return r }, result => {
  if (result.outcome === 'succeeded' && !result.error) message.value = `${item.source_ref}: trobada a Esfer@ (${result.remoteCode}); conciliada.`
  else if (result.outcome === 'failed') message.value = `${item.source_ref}: no hi és a Esfer@. Es pot tornar a executar.`
  else error.value = `${item.source_ref}: ${result.error}`
})
const diagnose = () => act('diagnose', async () => { await portal(); return platform.sferaExport!.diagnose() }, report => { diagnostic.value = report })

onMounted(() => act('list', async () => {
  await refreshList()
  const id = typeof route.query.pla === 'string' ? route.query.pla : plans.value[0]?.id
  if (id) plan.value = await exportApi.get(id).catch(() => null)
}))
</script>

<template>
  <div class="plans">
    <header class="page-head">
      <div><h1 class="page-title">Esfer@ · Plans d’exportació</h1><p class="page-lead">Revisió al Hub → aprovació → escriptura amb la teva sessió → relectura.</p></div>
      <div class="head-actions">
        <button class="btn btn-secondary" :disabled="!!busy || !desktop" @click="diagnose">{{ busy === 'diagnose' ? 'Comprovant…' : 'Diagnòstic' }}</button>
        <RouterLink class="btn btn-secondary" :to="{ name: 'sfera-invoice-poc' }">Prova d’extractes</RouterLink>
      </div>
    </header>
    <p v-if="error" class="notice notice-error" role="alert">{{ error }}</p>
    <p v-if="message" class="notice" role="status">{{ message }}</p>

    <section v-if="diagnostic" class="card panel diagnostic" aria-label="Diagnòstic">
      <div class="row-head"><h2>Diagnòstic · centre {{ diagnostic.centre }}</h2><span :class="['pill', diagnostic.ready ? 'ok' : 'fail']">{{ diagnostic.ready ? 'A punt per exportar' : 'Cal resoldre-ho' }}</span></div>
      <table class="compact"><tbody>
        <tr v-for="check in diagnostic.checks" :key="check.id" :data-check="check.id"><td class="status"><span :class="['dot', check.status]" :title="check.status" /></td><th>{{ check.label }}</th><td>{{ check.detail }}</td></tr>
      </tbody></table>
      <p class="text-muted">Només lectures: {{ diagnostic.requests.length }} peticions al portal, cap escriptura · {{ when(diagnostic.checkedAt) }}</p>
    </section>

    <div class="layout">
      <aside class="card list" aria-label="Plans">
        <p v-if="!plans.length" class="text-muted empty">Encara no hi ha plans. Prepara’n un des de la prova d’extractes.</p>
        <button v-for="p in plans" :key="p.id" :class="['plan-row', { active: plan?.id === p.id }]" @click="open(p.id)">
          <span class="mono">{{ p.id.slice(0, 8) }}</span><span :class="['pill', p.state]">{{ label(p.state) }}</span>
          <span class="text-muted">{{ p.items }} · {{ p.centre_code }} · {{ when(p.created_at) }}</span>
        </button>
      </aside>

      <section v-if="plan" class="card panel detail" aria-label="Detall del pla">
        <div class="row-head">
          <div><h2>Pla <span class="mono">{{ plan.id.slice(0, 8) }}</span> <span :class="['pill', plan.state]">{{ label(plan.state) }}</span></h2>
            <p class="text-muted">{{ plan.context.environment === 'training' ? 'Formació' : 'Producció' }} · centre {{ plan.context.centre_code }} · pressupost {{ plan.context.remote_budget_id }} ({{ plan.context.financial_year }}) · {{ plan.items.length }} factures · {{ euro(total) }}</p></div>
          <div class="head-actions">
            <button v-if="plan.state === 'ready'" class="btn btn-primary" :disabled="!!busy" @click="approve">Aprovar</button>
            <button v-if="pending.length" class="btn btn-primary" :disabled="!!busy || !desktop" @click="runAll">{{ busy === 'run-all' ? 'Executant…' : `Executar ${pending.length}` }}</button>
            <button v-if="['blocked','ready','approved','failed'].includes(plan.state)" class="btn btn-secondary" :disabled="!!busy" @click="cancel">Cancel·lar</button>
            <button v-if="deletable" class="btn btn-secondary danger" :disabled="!!busy" @click="remove">Eliminar</button>
          </div>
        </div>
        <p class="text-muted hash">Aprovació lligada a <span class="mono">{{ plan.plan_hash.slice(0, 16) }}…</span><template v-if="plan.approved_at"> · aprovat {{ when(plan.approved_at) }}</template></p>
        <div class="table-scroll"><table class="compact items">
          <thead><tr><th>Referència</th><th>Número</th><th>Data</th><th class="num">Import</th><th>Estat</th><th>Esfer@</th><th /></tr></thead>
          <tbody>
            <template v-for="item in plan.items" :key="item.id">
              <tr :data-item="item.source_ref">
                <td>{{ item.source_ref }}</td><td class="mono">{{ item.invoice.document_number }}</td><td>{{ item.invoice.accounting_date }}</td>
                <td class="num">{{ euro(item.invoice.total) }}</td><td><span :class="['pill', item.state]">{{ label(item.state) }}</span></td>
                <td class="mono">{{ item.remote_code || '—' }}</td>
                <td class="actions">
                  <button v-if="runnable(item)" class="btn btn-sm" :disabled="!!busy || !desktop" @click="run(item)">{{ item.state === 'failed' ? 'Reintentar' : 'Executar' }}</button>
                  <button v-if="['uncertain','conflict'].includes(item.state)" class="btn btn-sm" :disabled="!!busy || !desktop" @click="reconcile(item)">Conciliar</button>
                  <button v-if="item.state === 'executing'" class="btn btn-sm" :disabled="!!busy" @click="recover(item)">Recuperar</button>
                  <button v-if="!plan.approved_at && plan.items.length > 1" class="btn btn-sm" :disabled="!!busy" @click="removeItem(item)">Treure</button>
                </td>
              </tr>
              <tr v-for="(problem, i) in item.problems" :key="`${item.id}-p${i}`" class="problem"><td /><td colspan="6"><span :class="problem.blocking ? 'blocking' : 'warning'">{{ problem.blocking ? 'Bloqueja' : 'Avís' }}</span> {{ problem.message }} <span class="mono text-muted">{{ problem.field }}</span></td></tr>
              <tr v-for="attempt in item.attempts" :key="`${item.id}-a${attempt.id}`" class="attempt"><td /><td colspan="6" class="text-muted">Intent {{ attempt.id }} · {{ attempt.outcome }}<template v-if="attempt.http_status"> · HTTP {{ attempt.http_status }}</template> · {{ when(attempt.started_at) }}<template v-if="attempt.error"> · {{ attempt.error }}</template></td></tr>
            </template>
          </tbody>
        </table></div>
        <details v-if="lastRun?.requests.length"><summary>Peticions de l’última execució</summary>
          <table class="compact"><tbody><tr v-for="(r, i) in lastRun.requests" :key="i"><td class="mono">{{ r.method }} {{ r.path.replace('/bfgh/AppJava/bfgh_gesteco/services', '') }}</td><td>{{ r.status ?? '—' }}</td><td class="num">{{ r.durationMs }} ms</td><td>{{ r.error }}</td></tr></tbody></table>
        </details>
      </section>
    </div>
  </div>
</template>

<style scoped>
.plans { display: grid; gap: 14px; min-width: 0; }
.head-actions { display: flex; gap: 8px; flex-wrap: wrap; align-items: center; }
.layout { display: grid; grid-template-columns: minmax(220px, 280px) minmax(0, 1fr); gap: 14px; align-items: start; }
.panel { display: grid; gap: 10px; padding: 14px 16px; min-width: 0; }
.row-head { display: flex; justify-content: space-between; gap: 12px; align-items: flex-start; flex-wrap: wrap; }
h2 { font-size: var(--text-md, 15px); margin: 0; display: flex; gap: 8px; align-items: center; }
.list { display: grid; padding: 6px; gap: 2px; }
.empty { padding: 10px; }
.plan-row { display: grid; grid-template-columns: auto 1fr; gap: 2px 8px; text-align: left; padding: 8px; border: 0; background: none; border-radius: var(--r-sm, 4px); cursor: pointer; font: inherit; }
.plan-row .text-muted { grid-column: 1 / -1; font-size: 12px; }
.plan-row:hover { background: var(--surface-1); }
.plan-row.active { background: var(--surface-2, var(--surface-1)); box-shadow: inset 2px 0 0 var(--accent, #2563eb); }
.mono { font-family: var(--font-mono, ui-monospace, monospace); font-size: 12px; }
.pill { justify-self: start; font-size: 11px; padding: 1px 6px; border-radius: 3px; background: var(--surface-1); color: var(--ink-600, inherit); white-space: nowrap; }
.pill.ready, .pill.approved { background: color-mix(in srgb, #2563eb 12%, transparent); color: #1d4ed8; }
.pill.succeeded, .pill.reconciled, .pill.ok, .pill.finished { background: color-mix(in srgb, #15803d 14%, transparent); color: #15803d; }
.pill.blocked, .pill.failed, .pill.fail, .pill.conflict { background: color-mix(in srgb, #b91c1c 12%, transparent); color: #b91c1c; }
.pill.uncertain, .pill.executing { background: color-mix(in srgb, #b45309 14%, transparent); color: #b45309; }
.table-scroll { overflow-x: auto; }
table.compact { width: 100%; border-collapse: collapse; font-size: 13px; }
.compact th, .compact td { padding: 6px 8px; text-align: left; border-bottom: 1px solid var(--line); vertical-align: top; }
.compact th { font-weight: 600; white-space: nowrap; }
.num { text-align: right; font-variant-numeric: tabular-nums; }
.actions { white-space: nowrap; text-align: right; }
.actions .btn + .btn { margin-left: 4px; }
.btn-sm { padding: 3px 8px; font-size: 12px; }
.problem td, .attempt td { border-bottom: 0; padding-top: 0; font-size: 12px; }
.blocking { color: #b91c1c; font-weight: 600; } .warning { color: #b45309; font-weight: 600; }
.status { width: 18px; } .dot { display: inline-block; width: 8px; height: 8px; border-radius: 50%; background: #9ca3af; }
.dot.ok { background: #15803d; } .dot.warn { background: #b45309; } .dot.fail { background: #b91c1c; }
.danger { color: #b91c1c; }
.hash { font-size: 12px; margin: 0; }
summary { cursor: pointer; font-size: 13px; font-weight: 600; }
@media (max-width: 860px) { .layout { grid-template-columns: 1fr; } }
</style>
