<script setup lang="ts">
import { keepsPortal } from './portal-routes'
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { onBeforeRouteLeave } from 'vue-router'
import { usePlatform } from '../../platform'
import type { SferaBudget, SferaCell, SferaDataset, SferaQueryResult } from '../../sfera/contract'

const platform = usePlatform()
const dataset = ref<SferaDataset>('budgets')
const budgetId = ref<number | undefined>()
const budgets = ref<SferaBudget[]>([])
const result = ref<SferaQueryResult | null>(null)
const error = ref('')
const busy = ref(false)
const ready = ref(false)
const elapsed = ref(0)
const search = ref('')
const page = ref(1)
const detail = ref<Record<string, SferaCell> | null>(null)
const history = ref<{ label: string; rows: number; durationMs: number; time: string; ok: boolean }[]>([])
let alive = true, preservePortal = false, timer: ReturnType<typeof setInterval> | undefined
const labels: Record<SferaDataset,string> = { budgets: 'Pressupostos', suppliers: 'Proveïdors', invoices: 'Factures' }
const fields: Record<string,string> = {
  id: 'Identificador', any: 'Exercici', tipusPressupost: 'Tipus', estat: 'Estat', totalPressupostatIngres: 'Ingressos pressupostats', totalPressupostatDespesa: 'Despeses pressupostades', pendentExecutarIngres: 'Ingressos pendents', pendentExecutarDespesa: 'Despeses pendents', romanentExerciciAnterior: 'Romanent anterior', dataAprovacioPressupost: 'Aprovació', dataEstat: 'Data de l’estat',
  nifProveidor: 'NIF', nom: 'Nom', nomComercial: 'Nom comercial', nomMunicipi: 'Municipi', saldoProveidor: 'Saldo', codiCompte: 'Codi de compte', codiGeneratSistema: 'Codi', identificadorDocProveidor: 'Núm. de factura', identificadorDocCentre: 'Document intern', descripcio: 'Descripció', importTotalFinal: 'Import total', importEfectuat: 'Import pagat', importPendent: 'Import pendent', tipusDocument: 'Tipus de document', anulat: 'Anul·lada', liquidat: 'Liquidada', numAssentament: 'Assentament', proveidor: 'Proveïdor/a', dataDocument: 'Data del document', dataRegistre: 'Data comptable',
}
const displayColumns: Record<SferaDataset,string[]> = {
  budgets: ['any','tipusPressupost','estat','totalPressupostatIngres','totalPressupostatDespesa','dataEstat'],
  suppliers: ['nifProveidor','nom','nomComercial','nomMunicipi','estat','saldoProveidor'],
  invoices: ['dataRegistre','proveidor','identificadorDocProveidor','descripcio','importTotalFinal','importPendent','liquidat','anulat'],
}
const columns = computed(() => result.value ? displayColumns[result.value.dataset] : [])
const rows = computed(() => {
  const term = search.value.trim().toLocaleLowerCase('ca')
  return (result.value?.rows ?? []).filter(row => !term || Object.values(row).some(v => String(v ?? '').toLocaleLowerCase('ca').includes(term)))
})
const pages = computed(() => Math.max(1, Math.ceil(rows.value.length / 25)))
const visible = computed(() => rows.value.slice((page.value - 1) * 25, page.value * 25))
const invoiceTotal = computed(() => result.value?.dataset === 'invoices' ? result.value.rows.filter(r => r.anulat !== 'T').reduce((sum,r) => sum + (typeof r.importTotalFinal === 'number' ? r.importTotalFinal : 0),0) : null)
const moneyKeys = new Set(['totalPressupostatIngres','totalPressupostatDespesa','pendentExecutarIngres','pendentExecutarDespesa','romanentExerciciAnterior','saldoProveidor','importTotalFinal','importEfectuat','importPendent'])
const euro = (v: number) => new Intl.NumberFormat('ca-ES', { style: 'currency', currency: 'EUR' }).format(v)
function format(key: string, value: SferaCell | undefined): string {
  if (value == null || value === '') return '—'
  if (moneyKeys.has(key) && typeof value === 'number') return euro(value)
  if (['liquidat','anulat'].includes(key)) return value === 'T' ? 'Sí' : value === 'F' ? 'No' : String(value)
  if (key === 'tipusPressupost') return value === 'G' ? 'General' : value === 'M' ? 'Menjador' : String(value)
  if (key === 'estat' && result.value?.dataset === 'budgets') return value === 'A' ? 'Aprovat' : value === 'T' ? 'Validat i tancat' : String(value)
  if (key === 'estat' && result.value?.dataset === 'suppliers') return value === 'A' ? 'Actiu' : String(value)
  return String(value)
}
const duration = (ms: number) => ms < 1000 ? `${ms} ms` : `${(ms / 1000).toFixed(2)} s`
const time = (value: string) => new Date(value).toLocaleString('ca-ES')
watch([search,dataset], () => { page.value = 1; detail.value = null })
watch(rows, () => { page.value = Math.min(page.value,pages.value) })
async function query() {
  if (!platform.sferaData || !ready.value || busy.value) return
  busy.value = true; error.value = ''; detail.value = null; elapsed.value = 0
  const started = performance.now()
  timer = setInterval(() => { elapsed.value = Math.round(performance.now() - started) },100)
  try {
    const value = await platform.sferaData.query({ dataset: dataset.value, ...(dataset.value === 'invoices' && budgetId.value ? { budgetId: budgetId.value } : {}) })
    if (!alive) return
    result.value = value; page.value = 1
    budgets.value = value.budgets
    if (!budgets.value.some(b => b.id === budgetId.value)) budgetId.value = budgets.value[0]?.id
    error.value = value.error ?? ''
    history.value.unshift({ label: labels[value.dataset], rows: value.totalRows, durationMs: Math.round(performance.now() - started), time: value.completedAt, ok: !value.error })
    history.value = history.value.slice(0,8)
  } catch (e) {
    if (alive) {
      result.value = null; budgets.value = []; error.value = e instanceof Error ? e.message : 'No es pot completar la consulta.'
      history.value.unshift({ label: labels[dataset.value], rows: 0, durationMs: Math.round(performance.now() - started), time: new Date().toISOString(), ok: false })
      history.value = history.value.slice(0,8)
    }
  } finally { clearInterval(timer); if (alive) { elapsed.value = Math.round(performance.now() - started); busy.value = false } }
}
onBeforeRouteLeave(to => { preservePortal = keepsPortal(to.name) })
onMounted(async () => {
  try {
    const state = await platform.browser?.open('sfera')
    if (state && alive) { await platform.browser?.layout(state.id,null); if (alive) ready.value = true }
    else if (state && !preservePortal) await platform.browser?.close(state.id)
  } catch (e) { if (alive) error.value = e instanceof Error ? e.message : 'No es pot obrir la sessió.' }
})
onBeforeUnmount(() => {
  alive = false; clearInterval(timer)
  if (!preservePortal) void platform.browser?.release('sfera').catch(() => {})
})
</script>
<template>
  <div class="explorer">
    <header class="page-head"><div><h1 class="page-title">Esfer@ · Resum i dades</h1><p class="page-lead">Consulta i explora les dades del centre que has seleccionat a Esfer@.</p></div><RouterLink class="btn btn-secondary" :to="{ name: 'sfera' }">Obrir navegador</RouterLink></header>
    <p class="text-muted">Identifica’t i selecciona un centre al navegador. Les consultes utilitzen aquesta sessió i només llegeixen dades del portal de formació.</p>
    <section class="card query-controls" aria-label="Consulta de dades">
      <label>Dades<select v-model="dataset" class="input" :disabled="busy"><option value="budgets">Pressupostos</option><option value="suppliers">Proveïdors</option><option value="invoices">Factures</option></select></label>
      <label v-if="dataset === 'invoices'">Pressupost<select v-model="budgetId" class="input" :disabled="busy || !budgets.length"><option :value="undefined">Selecciona un pressupost</option><option v-for="b in budgets" :key="b.id" :value="b.id">{{ b.label }}</option></select></label>
      <button class="btn btn-primary" :disabled="busy || !ready || !platform.sferaData || (dataset === 'invoices' && !budgetId)" @click="query">{{ busy ? 'Consultant…' : result?.dataset === dataset ? 'Actualitzar dades' : 'Executar consulta' }}</button>
      <span role="status" aria-live="polite">{{ busy ? `Temps transcorregut: ${duration(elapsed)}` : history.length ? `Última consulta: ${duration(elapsed)}` : 'Executa una consulta per carregar les dades.' }}</span>
    </section>
    <div v-if="error" class="notice notice-error" role="alert">{{ error }}</div>
    <div v-if="!budgets.length && dataset === 'invoices'" class="notice">Consulta primer els pressupostos per escollir l’exercici de les factures.</div>
    <div v-if="result && !result.error" class="summary" aria-label="Resum de la consulta">
      <section class="card metric"><span>Centre d’Esfer@</span><strong>{{ result.centre }}</strong></section>
      <section class="card metric"><span>{{ labels[result.dataset] }}</span><strong>{{ result.totalRows.toLocaleString('ca-ES') }}</strong><small v-if="result.dataset === 'invoices'">Pressupost {{ result.budgets.find(b => b.id === result?.budgetId)?.label }}</small></section>
      <section class="card metric"><span>{{ invoiceTotal === null ? 'Pressupostos disponibles' : 'Import de factures no anul·lades' }}</span><strong>{{ invoiceTotal === null ? budgets.length : euro(invoiceTotal) }}</strong><small v-if="invoiceTotal !== null">Suma dels registres carregats</small></section>
      <section class="card metric"><span>Temps de les consultes a Esfer@</span><strong>{{ duration(result.durationMs) }}</strong><small>{{ time(result.completedAt) }}</small></section>
    </div>
    <section v-if="result && !result.error" class="card data-panel">
      <div class="data-head"><h2>{{ labels[result.dataset] }}</h2><label class="search">Cerca als resultats<input v-model="search" class="input" type="search" placeholder="Nom, codi, descripció…" /></label></div>
      <p v-if="result.truncated" class="notice">Es mostren els primers 10.000 registres. Els totals del resum fan referència a les files carregades.</p>
      <p role="status">{{ rows.length.toLocaleString('ca-ES') }} registres{{ search ? ' que coincideixen' : ' carregats' }} · pàgina {{ page }} de {{ pages }}</p>
      <div class="table-scroll"><table><thead><tr><th v-for="key in columns" :key="key" scope="col">{{ fields[key] }}</th><th scope="col">Detall</th></tr></thead><tbody><tr v-for="(row,index) in visible" :key="String(row.id ?? index)"><td v-for="key in columns" :key="key">{{ format(key,row[key]) }}</td><td><button class="btn btn-ghost" :aria-label="`Veure detall del registre ${row.id ?? index + 1}`" @click="detail = row">Veure</button></td></tr><tr v-if="!visible.length"><td :colspan="columns.length + 1">{{ search ? 'Cap resultat coincideix amb la cerca.' : 'Esfer@ no ha retornat cap registre per a aquesta consulta.' }}</td></tr></tbody></table></div>
      <div class="pagination"><button class="btn btn-secondary" :disabled="page <= 1" @click="page--">Anterior</button><span>{{ page }} / {{ pages }}</span><button class="btn btn-secondary" :disabled="page >= pages" @click="page++">Següent</button></div>
      <section v-if="detail" class="detail"><div class="data-head"><h3>Detall del registre</h3><button class="btn btn-ghost" @click="detail = null">Tancar detall</button></div><dl><template v-for="(value,key) in detail" :key="key"><dt>{{ fields[key] ?? key }}</dt><dd>{{ format(key,value) }}</dd></template></dl></section>
    </section>
    <section v-else-if="!error" class="card empty"><h2>Les dades apareixeran aquí</h2><p>Comença amb els pressupostos. Després podràs consultar els proveïdors del centre o les factures d’un pressupost.</p></section>
    <details v-if="result?.requests.length || history.length" class="card request-panel"><summary>Peticions i temps</summary><p>El temps total inclou la verificació del compte de Cosecre. Cada petició mostra el temps de resposta i lectura d’Esfer@.</p><div v-if="result?.requests.length" class="table-scroll"><table><thead><tr><th>Petició</th><th>Resposta</th><th>Registres</th><th>Temps</th></tr></thead><tbody><tr v-for="(request,index) in result.requests" :key="index"><td><code>{{ request.method }} {{ request.path }}</code></td><td>{{ request.status ?? 'Sense resposta' }}</td><td>{{ request.rows ?? '—' }}</td><td>{{ duration(request.durationMs) }}</td></tr></tbody></table></div><h3>Consultes d’aquesta sessió</h3><ul><li v-for="(run,index) in history" :key="index">{{ time(run.time) }} · {{ run.label }} · {{ run.ok ? `${run.rows} registres` : 'Consulta no completada' }} · {{ duration(run.durationMs) }}</li></ul></details>
    <p class="text-muted">Les dades es mantenen en aquesta pantalla mentre l’explores. No es desen al Hub. Aquesta eina no modifica ni registra factures a Esfer@.</p>
  </div>
</template>
<style scoped>
.explorer { display: grid; gap: 18px; min-width: 0; }
.query-controls { display: flex; align-items: end; flex-wrap: wrap; gap: 16px; padding: 20px; }
label { display: grid; gap: 6px; font-size: var(--text-sm); }
select, input { min-width: 220px; }
.summary { display: grid; grid-template-columns: repeat(4,minmax(0,1fr)); gap: 14px; }
.metric { display: grid; align-content: start; gap: 8px; padding: 20px; }
.metric span, .metric small { color: var(--ink-500); }
.metric strong { font-size: 24px; overflow-wrap: anywhere; }
.data-panel, .empty, .request-panel { padding: 20px; display: grid; gap: 14px; min-width: 0; }
.data-head { display: flex; align-items: center; justify-content: space-between; gap: 16px; flex-wrap: wrap; }
.table-scroll { overflow-x: auto; }
table { border-collapse: collapse; width: 100%; font-size: var(--text-sm); }
th, td { padding: 10px 12px; text-align: left; border-bottom: 1px solid var(--line); }
th { white-space: nowrap; color: var(--ink-500); }
td { max-width: 320px; overflow-wrap: anywhere; }
.pagination { display: flex; justify-content: flex-end; align-items: center; gap: 12px; }
.detail { border-top: 1px solid var(--line); padding-top: 16px; }
dl { display: grid; grid-template-columns: minmax(140px,1fr) 2fr; gap: 10px 20px; margin-top: 12px; }
dt { color: var(--ink-500); } dd { margin: 0; overflow-wrap: anywhere; }
summary { cursor: pointer; font-weight: 600; }
code { font-size: 12px; overflow-wrap: anywhere; }
@media (max-width: 1000px) { .summary { grid-template-columns: repeat(2,minmax(0,1fr)); } }
@media (max-width: 640px) { .summary { grid-template-columns: 1fr; } select, input { min-width: 0; width: 100%; } }
</style>
