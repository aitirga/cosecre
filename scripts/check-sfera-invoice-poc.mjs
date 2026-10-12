/** Domain tests for the synthetic statement → Sfer@ invoice PoC; no network. */
import assert from 'node:assert/strict'
import { build } from 'esbuild'

const built=await build({entryPoints:['frontend/src/sfera/invoice-poc.ts'],bundle:true,write:false,platform:'node',format:'esm'})
const {generatePocMovements,preparePocInvoices,SyntheticSferaTransport,executePocInvoices}=await import('data:text/javascript;base64,'+Buffer.from(built.outputFiles[0].text).toString('base64'))
let checks=0
function check(name,fn) { fn();checks++;console.log('✓',name) }
const sample=generatePocMovements(), prepared=preparePocInvoices(sample)
check('Debits become two invoice DTOs; the credit is excluded',()=>{assert.equal(prepared.invoices.length,2);assert.deepEqual(prepared.excluded,['M003']);assert.equal(Math.round(prepared.invoices.reduce((n,r)=>n+r.importTotalFinal,0)*100),16095)})
for(const [name,value] of [['zero',0],['over limit',-201],['fractional cent',-1.001],['non-finite',NaN]]) check('Invalid movement amount: '+name,()=>assert.throws(()=>preparePocInvoices([{...sample[0],amount:value}])))
check('Invalid calendar date rejected',()=>assert.throws(()=>preparePocInvoices([{...sample[0],date:'2026-02-30'}])))
check('Duplicate source movement rejected',()=>assert.throws(()=>preparePocInvoices([sample[0],sample[0]])))
check('Unknown supplier rejected before submission',()=>assert.throws(()=>preparePocInvoices([{...sample[0],supplierId:999}])))
const mock=new SyntheticSferaTransport(), trace=[]
const saved=await executePocInvoices(mock,prepared.invoices,t=>trace.push(t))
check('Validate, save and read back the exact two amounts',()=>{assert.equal(saved.length,2);assert.equal(saved[0].amount,121);assert.equal(saved[1].amount,39.95);assert.equal(trace.filter(t=>t.path.endsWith('/validate')).length,2);assert.equal(trace.filter(t=>t.path.endsWith('/desa')).length,2)})
const again=await executePocInvoices(mock,prepared.invoices,()=>{})
check('Repeating the same statement does not duplicate invoices',()=>assert.equal(again.length,2))
const badLine=structuredClone(prepared.invoices[0]);badLine.partidasFactura[0].importBase=1
const wrongLine=await mock.request('PUT','/services/factura/validate',badLine)
check('Line total mismatch rejected by the simulator',()=>assert.equal(wrongLine.status,422))
const badDue=structuredClone(prepared.invoices[0]);badDue.vencimentsFactura[0].import_=10
const wrongDue=await mock.request('PUT','/services/factura/validate',badDue)
check('Maturity total mismatch rejected by the simulator',()=>assert.equal(wrongDue.status,422))
const badContext=structuredClone(prepared.invoices[0]);badContext.pressupost.id=999
const wrongContext=await mock.request('PUT','/services/factura/desa',badContext)
check('Real budget IDs cannot be used in the simulator',()=>assert.equal(wrongContext.status,422))
const badPaid=structuredClone(prepared.invoices[0]);badPaid.vencimentsFactura[0].liquidat='T'
const wrongPaid=await mock.request('PUT','/services/factura/desa',badPaid)
check('Paid invoices rejected by this PoC',()=>assert.equal(wrongPaid.status,422))
const badLength=structuredClone(prepared.invoices[0]);badLength.identificadorDocProveidor='CSC-POC-'+'X'.repeat(13)
const wrongLength=await mock.request('PUT','/services/factura/validate',badLength)
check('Invoice numbers over Esfer@\'s 20 characters rejected before saving',()=>{assert.equal(wrongLength.status,422);assert(prepared.invoices.every(i=>i.identificadorDocProveidor.length<=20))})
const attempts=[]
await assert.rejects(executePocInvoices({request:async(method,path)=>{attempts.push(path);return path.endsWith('/creades')?{status:200,data:[]}:{status:422,data:{errors:['intentional validation failure']}}}},prepared.invoices,()=>{}))
check('Failed validation prevents any save call',()=>assert.equal(attempts.some(p=>p.endsWith('/desa')),false))
const contractBuild=await build({entryPoints:['frontend/src/sfera/export-contract.ts'],bundle:true,write:false,platform:'node',format:'esm'})
const {contractFromPocPlan,isoDate}=await import('data:text/javascript;base64,'+Buffer.from(contractBuild.outputFiles[0].text).toString('base64'))
// A reviewed real plan: what the desktop's prepare() returns after mapping to live catalog IDs.
const realInvoices=structuredClone(prepared.invoices).map(i=>({...i,pressupost:{id:901,any:2026,idCentre:900},partidasFactura:i.partidasFactura.map(l=>({...l,partidaPressupost:{id:2001},centreCost:{id:7001}})),vencimentsFactura:i.vencimentsFactura.map(v=>({...v,compteBancari:{id:7002}}))}))
const contract=contractFromPocPlan({id:'p',centre:'00000001',budget:'2026 · General',bank:'General',invoices:realInvoices,suppliers:[]})
check('Reviewed plan → Hub contract: context from the plan, decimals as strings, ISO dates, cost centre kept',()=>{
  assert.deepEqual(contract.context,{environment:'training',centre_code:'00000001',remote_centre_id:900,remote_budget_id:901,financial_year:2026,vat_settlement:false})
  const [first]=contract.invoices
  assert.equal(first.total,'121.00');assert.equal(first.lines[0].base,'121.00');assert.equal(first.lines[0].vat_amount,'0.00');assert.equal(first.lines[0].cost_centre_remote_id,7001)
  assert.match(first.accounting_date,/^\d{4}-\d{2}-\d{2}$/);assert.equal(first.due_dates[0].payment_type,'TR');assert.equal(first.due_dates[0].bank_account_remote_id,7002)
  assert.equal(first.document_number,realInvoices[0].identificadorDocProveidor);assert(first.document_number.length<=20)
})
check('Contract conversion refuses mixed budgets and malformed dates',()=>{
  const mixed=structuredClone(realInvoices);mixed[1].pressupost.id=1
  assert.throws(()=>contractFromPocPlan({id:'p',centre:'00000001',budget:'',bank:'',invoices:mixed,suppliers:[]}),/mateix pressupost/)
  assert.throws(()=>isoDate('2026-10-12'));assert.equal(isoDate('12/10/2026'),'2026-10-12')
})
console.log(JSON.stringify({passed:checks,networkRequests:0,mode:'synthetic'},null,2))
