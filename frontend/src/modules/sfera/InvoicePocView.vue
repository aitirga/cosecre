<script setup lang="ts">
import { keepsPortal } from './portal-routes'
import { computed, onBeforeUnmount, ref } from 'vue'
import { onBeforeRouteLeave, useRouter } from 'vue-router'
import { usePlatform } from '../../platform'
import type { InvoiceCatalog, InvoicePlan, InvoiceWriteTrace } from '../../sfera/invoice-bridge'
import { contractFromPocPlan } from '../../sfera/export-contract'
import { exportApi } from './export-api'
import { POC_CATALOG, SyntheticSferaTransport, executePocInvoices, generatePocMovements, preparePocInvoices, type PocCreated, type PocInvoice, type PocMovement, type PocTrace } from '../../sfera/invoice-poc'

const movements = ref<PocMovement[]>(generatePocMovements())
const drafts = ref<PocInvoice[]>([])
const excluded = ref<string[]>([])
const created = ref<PocCreated[]>([])
const traces = ref<PocTrace[]>([])
const error = ref('')
const message = ref('')
const busy = ref(false)
const elapsed = ref(0)
let transport = new SyntheticSferaTransport()
const platform=usePlatform()
const router=useRouter()
const connected=ref(false)
const catalog=ref<InvoiceCatalog|null>(null)
const budgetId=ref<number>()
const bankId=ref<number>()
const realPlan=ref<InvoicePlan|null>(null)
const realTraces=ref<InvoiceWriteTrace[]>([])
let alive=true, preservePortal=false
onBeforeRouteLeave(to=>{preservePortal=keepsPortal(to.name)})
onBeforeUnmount(()=>{alive=false;if(!preservePortal) void platform.browser?.release('sfera').catch(()=>{})})
const supplierChoices=computed(()=>connected.value?(catalog.value?.suppliers??[]).map(s=>({id:s.id,name:s.label})):POC_CATALOG.suppliers)
const partidaChoices=computed(()=>connected.value?(catalog.value?.partidas??[]).map(s=>({id:s.id,name:s.label})):POC_CATALOG.partidas)
const prepareIssue=computed(()=>{
  const expenses=movements.value.filter(m=>m.amount<0)
  if(!expenses.length) return 'Cal almenys un moviment amb import negatiu per preparar una factura.'
  if(connected.value) {
    const supplier=expenses.find(m=>!catalog.value?.suppliers.some(s=>s.id===m.supplierId))
    if(supplier) return `${supplier.id}: selecciona un proveïdor del centre.`
    const partida=expenses.find(m=>!catalog.value?.partidas.some(p=>p.id===m.partidaId))
    if(partida) return `${partida.id}: selecciona una partida del pressupost.`
  }
  return ''
})
const readableError=(e:unknown,fallback:string)=>e instanceof Error?e.message.replace(/^Error invoking remote method '[^']+': Error: /,''):fallback
async function loadConnected() {
  busy.value=true;error.value='';created.value=[];realPlan.value=null;drafts.value=[]
  try {
    const state=await platform.browser?.open('sfera')
    if(state) await platform.browser?.layout(state.id,null)
    const value=await platform.sferaInvoices?.catalog(budgetId.value)
    if(value&&alive) {
      catalog.value=value;budgetId.value=value.budgetId;bankId.value=value.banks[0]?.id;connected.value=true
      movements.value.forEach(m=>{m.supplierId=0;m.partidaId=0})
      message.value='Catàlegs reals carregats. Selecciona el proveïdor i la partida de cada despesa.'
    }
  } catch(e) {if(alive) error.value=e instanceof Error?e.message:'No es pot connectar al portal.'}
  finally {if(alive) busy.value=false}
}
const euro = (v: number) => new Intl.NumberFormat('ca-ES',{style:'currency',currency:'EUR'}).format(v)
const total = computed(() => drafts.value.reduce((sum,draft) => sum + Math.round(draft.importTotalFinal * 100),0) / 100)
function reset() {
  movements.value = generatePocMovements(); drafts.value = []; excluded.value = []; created.value = []; traces.value = []; error.value = ''; message.value = ''; elapsed.value = 0
  transport = new SyntheticSferaTransport()
  realPlan.value=null;realTraces.value=[]
  if(connected.value) movements.value.forEach(m=>{m.supplierId=0;m.partidaId=0})
}
function invalidateDrafts() { drafts.value = []; realPlan.value=null;excluded.value = []; error.value = ''; message.value = '' }
async function prepare() {
  if(prepareIssue.value) {error.value=prepareIssue.value;return}
  if(connected.value) {
    busy.value=true;error.value=''
    try {
      if(!budgetId.value||!bankId.value||!platform.sferaInvoices) throw Error('Selecciona pressupost i banc.')
      const plan=await platform.sferaInvoices.prepare({budgetId:budgetId.value,bankId:bankId.value,movements:movements.value.map(m=>({...m}))})
      if(alive) {realPlan.value=plan;drafts.value=plan.invoices;excluded.value=movements.value.filter(m=>m.amount>0).map(m=>m.id);message.value='Revisió preparada amb dades reals. Crear a Esfer@ desarà aquestes factures al portal de formació.'}
    } catch(e) {if(alive){drafts.value=[];error.value=readableError(e,'No es pot preparar la revisió.')}}
    finally {if(alive) busy.value=false}
    return
  }
  try {
    const result = preparePocInvoices(movements.value)
    drafts.value = result.invoices; excluded.value = result.excluded; traces.value = []; error.value = ''
    message.value = `${result.invoices.length} factures preparades. Revisa els imports i els camps abans d’executar la prova.`
  } catch(e) { drafts.value = []; error.value = e instanceof Error ? e.message : 'No es poden preparar les factures.' }
}
/** The reviewed real plan as a Hub export plan: checked, approved and run from «Plans d'exportació». */
async function createHubPlan() {
  if(busy.value||!realPlan.value) return
  busy.value=true;error.value=''
  try {
    const {context,invoices}=contractFromPocPlan(realPlan.value)
    const plan=await exportApi.create(context,invoices)
    preservePortal=true
    await router.push({name:'sfera-plans',query:{pla:plan.id}})
  } catch(e) {if(alive) error.value=readableError(e,'No es pot crear el pla al Hub.')}
  finally {if(alive) busy.value=false}
}
async function run() {
  if(busy.value || !drafts.value.length) return
  busy.value = true; error.value = ''; message.value = ''; traces.value = []
  const start = performance.now()
  try {
    if(connected.value) {
      if(!realPlan.value||!platform.sferaInvoices) throw Error('Torna a preparar les factures.')
      const result=await platform.sferaInvoices.create(realPlan.value.id)
      created.value=result.records;realTraces.value=result.requests
      if(result.error) throw Error(result.error)
      message.value=`${result.records.length} factures creades i comprovades a Esfer@ de formació. Sense executar pagaments.`
    } else {
      created.value = await executePocInvoices(transport,drafts.value,entry => traces.value.push(entry))
      message.value = `${created.value.length} factures creades i rellegides al simulador. Els imports coincideixen amb els esborranys.`
    }
  } catch(e) { error.value = e instanceof Error ? e.message : 'No es pot completar la prova.' }
  finally { elapsed.value = Math.round((performance.now() - start) * 100) / 100; busy.value = false }
}
</script>
<template>
  <div class="poc">
    <header class="page-head"><div><h1 class="page-title">Sfer@ · Prova d’extractes</h1><p class="page-lead">Moviments ficticis → esborranys → validació → factures de prova.</p></div><RouterLink class="btn btn-secondary" :to="{name:'sfera-data'}">Resum i dades</RouterLink></header>
    <div v-if="!connected" class="notice notice-gold"><strong>Prova sintètica local</strong><p>El simulador no envia factures al portal. Pots connectar el desament al portal de formació amb la sessió oberta al navegador.</p><button class="btn btn-secondary" :disabled="busy || !platform.sferaInvoices" @click="loadConnected">Connectar amb Esfer@ de formació</button></div>
    <section v-else class="card panel"><h2>Connexió real · portal de formació</h2><p>Centre {{ catalog?.centre }}. Les factures es desaran a Esfer@ amb el prefix CSC-POC i quedaran pendents, sense pagament.</p><div class="section-head"><label>Pressupost<select v-model="budgetId" class="select" :disabled="busy" @change="loadConnected"><option v-for="b in catalog?.budgets" :key="b.id" :value="b.id">{{ b.label }}</option></select></label><label>Banc<select v-model="bankId" class="select" :disabled="busy" @change="invalidateDrafts"><option v-for="b in catalog?.banks" :key="b.id" :value="b.id">{{ b.label }}</option></select></label><RouterLink class="btn btn-secondary" :to="{name:'sfera'}">Obrir navegador</RouterLink></div></section>
    <section class="card panel"><div class="section-head"><h2>1. Extracte de prova</h2><button class="btn btn-secondary" :disabled="busy" @click="reset">Generar extracte fictici</button></div><p>Edita els conceptes o els imports per provar altres casos. Els imports negatius es preparen com a despeses; els ingressos queden exclosos.</p><div class="table-scroll"><table><thead><tr><th>Moviment</th><th>Data</th><th>Concepte</th><th>Import</th><th>Proveïdor</th><th>Partida</th></tr></thead><tbody><tr v-for="m in movements" :key="m.id"><td>{{ m.id }}</td><td><input v-model="m.date" class="input" type="date" :aria-label="`Data ${m.id}`" :disabled="busy" @change="invalidateDrafts" /></td><td><input v-model="m.description" class="input concept" :aria-label="`Concepte ${m.id}`" :disabled="busy" @input="invalidateDrafts" /></td><td><input v-model.number="m.amount" class="input amount" type="number" step="0.01" :aria-label="`Import ${m.id}`" :disabled="busy" @input="invalidateDrafts" /></td><td><select v-model.number="m.supplierId" class="select" :aria-label="`Proveïdor ${m.id}`" :disabled="busy || m.amount > 0" @change="invalidateDrafts"><option v-if="connected" :value="0">Selecciona un proveïdor</option><option v-for="s in supplierChoices" :key="s.id" :value="s.id">{{ s.name }}</option></select></td><td><select v-model.number="m.partidaId" class="select" :aria-label="`Partida ${m.id}`" :disabled="busy || m.amount > 0" @change="invalidateDrafts"><option v-if="connected" :value="0">Selecciona una partida</option><option v-for="p in partidaChoices" :key="p.id" :value="p.id">{{ p.name }}</option></select></td></tr></tbody></table></div><button class="btn btn-primary action" :disabled="busy" @click="prepare">Preparar factures</button></section>
    <p v-if="error" class="notice notice-error" role="alert">{{ error }}</p><p v-if="message" class="notice" role="status">{{ message }}</p>
    <section v-if="drafts.length" class="card panel"><h2>2. Revisió dels esborranys</h2><p>{{ realPlan ? `Centre ${realPlan.centre} · ${realPlan.budget} · ${realPlan.bank}` : `${POC_CATALOG.centre.name} · ${POC_CATALOG.budget.name} · ${POC_CATALOG.bank.name}` }}</p><div class="summary"><div><span>Factures</span><strong>{{ drafts.length }}</strong></div><div><span>Import total</span><strong>{{ euro(total) }}</strong></div><div><span>Moviments exclosos</span><strong>{{ excluded.length }}</strong></div></div><p v-if="excluded.length">{{ excluded.join(', ') }}: ingrés, no es converteix en factura de despesa.</p><div class="table-scroll"><table><thead><tr><th>Número de prova</th><th>Proveïdor</th><th>Descripció</th><th>Import</th><th>Estat</th></tr></thead><tbody><tr v-for="d in drafts" :key="d.identificadorDocProveidor"><td>{{ d.identificadorDocProveidor }}</td><td>{{ supplierChoices.find(s=>s.id===d.proveidor.id)?.name }}</td><td>{{ d.descripcio }}</td><td>{{ euro(d.importTotalFinal) }}</td><td>Pendent</td></tr></tbody></table></div><p class="text-muted">La prova fixa IVA deduïble i IRPF a zero i crea un venciment pendent per l’import total. Els proveïdors i les partides han d’estar revisats abans de crear les factures.</p><div class="section-head"><button class="btn btn-primary action" :disabled="busy" @click="run">{{ busy ? 'Executant…' : connected ? 'Crear aquestes factures a Esfer@ de formació' : 'Executar prova sintètica' }}</button><button v-if="realPlan" class="btn btn-secondary" :disabled="busy" @click="createHubPlan">Crear un pla al Hub per revisar-lo</button></div><details><summary>Camps preparats per a Esfer@</summary><pre>{{ JSON.stringify(drafts,null,2) }}</pre></details></section>
    <section v-if="created.length" class="card panel"><h2>3. Factures creades i comprovades</h2><p>{{ created.length }} registres {{ connected ? 'a Esfer@ de formació' : 'al simulador' }} · {{ elapsed }} ms · repetir la prova comprova les factures i evita duplicats.</p><div class="table-scroll"><table><thead><tr><th>Identificador</th><th>Codi generat</th><th>Número de factura</th><th>Import</th></tr></thead><tbody><tr v-for="r in created" :key="r.id"><td>{{ r.id }}</td><td>{{ r.code }}</td><td>{{ r.number }}</td><td>{{ euro(r.amount) }}</td></tr></tbody></table></div></section>
    <details v-if="realTraces.length" class="card panel"><summary>Peticions reals i temps</summary><table><thead><tr><th>Petició</th><th>Resposta</th><th>Temps</th></tr></thead><tbody><tr v-for="(trace,index) in realTraces" :key="index"><td>{{ trace.method }} {{ trace.path }}</td><td>{{ trace.status??'Sense resposta' }}</td><td>{{ trace.durationMs }} ms</td></tr></tbody></table></details>
    <details v-if="traces.length" class="card panel"><summary>Peticions simulades i temps</summary><p>Aquestes durades corresponen al simulador local, sense temps de xarxa. La validació i el desament segueixen les rutes observades al portal; la relectura de prova és pròpia del simulador.</p><div class="table-scroll"><table><thead><tr><th>Petició</th><th>Resposta</th><th>Temps</th><th>Resultat</th></tr></thead><tbody><tr v-for="(trace,index) in traces" :key="index"><td><code>{{ trace.method }} {{ trace.path }}</code></td><td>{{ trace.status }}</td><td>{{ trace.durationMs }} ms</td><td>{{ trace.message }}</td></tr></tbody></table></div></details>
  </div>
</template>
<style scoped>
.poc { display:grid; gap:18px; min-width:0; }
.panel { display:grid; gap:16px; padding:20px; min-width:0; }
.section-head { display:flex; gap:16px; align-items:center; justify-content:space-between; flex-wrap:wrap; }
.table-scroll { overflow-x:auto; }
table { width:100%; border-collapse:collapse; font-size:var(--text-sm); }
th,td { padding:10px; text-align:left; border-bottom:1px solid var(--line); } th { white-space:nowrap; }
td { min-width:90px; } .concept { min-width:230px; } .amount { min-width:105px; } input[type=date] { min-width:140px; } select { min-width:180px; }
.action { justify-self:start; } .summary { display:grid; grid-template-columns:repeat(3,1fr); gap:20px; }
.summary div { display:grid; gap:8px; padding:16px; background:var(--surface-1); border-radius:var(--r-md); }
.summary strong { font-size:24px; } .summary span { color:var(--ink-500); }
summary { cursor:pointer; font-weight:600; } pre { overflow:auto; max-height:420px; padding:16px; background:var(--surface-1); margin-top:12px; font-size:12px; }
@media(max-width:640px) { .summary { grid-template-columns:1fr; } }
</style>
