import { randomUUID } from 'node:crypto'
import type { WebContents } from 'electron'
import type { InvoiceCatalog, InvoiceCommitResult, InvoicePlan, SferaInvoiceBridge } from '../../../../frontend/src/sfera/invoice-bridge'
import { preparePocInvoices, sferaLimitErrors, type PocInvoice, type PocCreated } from '../../../../frontend/src/sfera/invoice-poc'
import { connectPortal, PortalError, type PortalConnection } from './portal'
type Row = Record<string, any>
type OwnedPlan = { viewId: number; centre: string; signature: string; budgetId: number; invoices: PocInvoice[]; result: InvoicePlan }
const rows = (v: unknown): Row[] => {
  if(!Array.isArray(v) || v.some(r=>!r || !Number.isSafeInteger(r.id))) throw new PortalError('El format del catàleg d’Esfer@ ha canviat.')
  return v as Row[]
}
const signature = (c: PortalConnection) => JSON.stringify(['TOKEN','USR_CENTRE','USR_ROL','USR_USERNAME_AWA'].map(k=>c.access.headers[k]))
const invoiceFilter = (budgetId: number, number: string | null = null) => ({proveidor:'',numFactura:number,partidaSubpartidaExtrapressupostari:null,reserva:'',numDocIntern:null,numDocReferencia:null,dataVencimentDesde:null,dataVencimentFinsa:null,dataRegistreDesde:'2026/01/01',dataRegistreFinsa:'2026/12/31',descripcio:null,despesaSimplificada:'F',idPressupost:budgetId})

export class SferaInvoices {
  private plans = new Map<string,OwnedPlan>()
  clear() { this.plans.clear() }
  private async catalogs(connection: PortalConnection,budgetId?: number) {
    const budgets=rows(await connection.request('GET','/pressupost/centre')).filter(b=>b.any===2026 && ['A','P'].includes(b.estat))
    const budget=budgetId?budgets.find(b=>b.id===budgetId):budgets.find(b=>b.tipusPressupost==='G')??budgets[0]
    if(!budget) throw new PortalError('Selecciona un pressupost editable de 2026 del centre actual.')
    const [suppliers,partidas,banks,vat]=await Promise.all([
      connection.request('GET','/proveidor/cerca'),
      connection.request('GET',`/partidaPressupost/cerca/filtre/${budget.id}/DESPESA`),
      connection.request('GET','/compteBancari/comptesActiuVigent?exercici=2026&actiu=A'),
      connection.request('GET','/parametresCentre/liquidacioIVA?exercici=2026'),
    ])
    if ((vat as Row)?.valor==='T') throw new PortalError('Aquest centre liquida IVA. Aquesta prova necessita un tractament fiscal revisat abans de crear factures.')
    const catalog: InvoiceCatalog = {centre:connection.access.centre,budgetId:budget.id,budgets:budgets.map(b=>({id:b.id,label:`${b.any} · ${b.tipusPressupost==='G'?'General':'Menjador'}`})),suppliers:rows(suppliers).filter(s=>s.estat==='A').map(s=>({id:s.id,label:String(s.nom)})),partidas:rows(partidas).map(p=>({id:p.id,label:`${p.codiPartida??p.codi??''} · ${p.nom??p.descripcio??p.nomPartida??''}`})),banks:rows(banks).map(b=>({id:b.id,label:String(b.nomDescriptiuCompte??b.nom??b.nomCompte??b.descripcio??b.codiIntern??b.id)}))}
    await connection.assertContext()
    return {catalog,budget,partidas:rows(partidas),banks:rows(banks)}
  }
  async catalog(wc:WebContents,url:string,valid:()=>boolean,budgetId?:number) {
    if(budgetId!==undefined && (!Number.isSafeInteger(budgetId)||budgetId<=0)) throw new PortalError('Pressupost no vàlid.')
    return (await this.catalogs(await connectPortal(wc,url,valid),budgetId)).catalog
  }
  async prepare(wc:WebContents,url:string,valid:()=>boolean,input:Parameters<SferaInvoiceBridge['prepare']>[0]):Promise<InvoicePlan> {
    if(!input || Object.keys(input).some(k=>!['budgetId','bankId','movements'].includes(k)) || !Number.isSafeInteger(input.budgetId) || !Number.isSafeInteger(input.bankId) || !Array.isArray(input.movements) || input.movements.length<1 || input.movements.length>3) throw new PortalError('Dades de prova no vàlides.')
    const connection=await connectPortal(wc,url,valid)
    const {catalog,budget,partidas,banks}=await this.catalogs(connection,input.budgetId)
    const bank=banks.find(b=>b.id===input.bankId)
    if(!bank || !Number.isSafeInteger(budget.idCentre)) throw new PortalError('Selecciona un banc del centre actual.')
    const mapped=preparePocInvoices(input.movements.map(m=>({...m,supplierId:1001,partidaId:2001})))
    if(mapped.invoices.length>2) throw new PortalError('La prova permet crear un màxim de dues factures.')
    const id=randomUUID()
    for(const invoice of mapped.invoices) {
      const m=input.movements.find(m=>invoice.identificadorDocCentre===`POC-${m.id}`)!
      if(!catalog.suppliers.some(s=>s.id===m.supplierId)) throw new PortalError('Selecciona un proveïdor actiu del centre.')
      const partida=partidas.find(p=>p.id===m.partidaId)
      if(!partida) throw new PortalError('Selecciona una partida del pressupost actual.')
      invoice.pressupost={id:budget.id,any:2026,idCentre:budget.idCentre}
      invoice.proveidor={id:m.supplierId}
      // Esfer@ needs the line's cost centre; without it validation fails server-side
      // and the PUT surfaces as a misleading 405 "HTTP method PUT is not supported".
      const costCentres=Array.isArray(partida.centreCostDesglosPartida)?partida.centreCostDesglosPartida.filter((c:Row)=>Number.isSafeInteger(c?.id)):[]
      if(costCentres.length!==1) throw new PortalError(costCentres.length?'La partida té més d’un centre de cost. Aquesta prova només admet partides amb un únic centre de cost.':'La partida no té cap centre de cost assignat a Esfer@.')
      invoice.partidasFactura[0].partidaPressupost={id:partida.id}
      invoice.partidasFactura[0].centreCost={id:costCentres[0].id}
      invoice.vencimentsFactura[0].compteBancari={id:bank.id}
      // Esfer@ keeps at most 20 characters for the invoice number: CSC-POC-xxxxxx-M001 is 19.
      invoice.identificadorDocProveidor=`CSC-POC-${id.slice(0,6)}-${m.id}`
      invoice.observacions='COSECRE POC. Dades fictícies creades al portal de formació per comprovar la integració. Factura pendent, sense pagament.'
      const tooLong=sferaLimitErrors(invoice)
      if(tooLong.length) throw new PortalError(`Dades massa llargues per a Esfer@. ${tooLong.join(' ')}`)
    }
    await connection.assertContext()
    const result:InvoicePlan={id,centre:catalog.centre,budget:catalog.budgets.find(b=>b.id===budget.id)!.label,bank:catalog.banks.find(b=>b.id===bank.id)!.label,invoices:structuredClone(mapped.invoices),suppliers:catalog.suppliers.filter(s=>mapped.invoices.some(i=>i.proveidor.id===s.id))}
    this.plans.set(id,{viewId:wc.id,centre:catalog.centre,signature:signature(connection),budgetId:budget.id,invoices:structuredClone(mapped.invoices),result})
    return result
  }
  async create(wc:WebContents,url:string,valid:()=>boolean,id:unknown):Promise<InvoiceCommitResult> {
    const plan=typeof id==='string'?this.plans.get(id):undefined
    if(!plan || plan.viewId!==wc.id) throw new PortalError('La revisió de la factura ha caducat. Torna a preparar-la.')
    const result:InvoiceCommitResult={records:[],requests:[],error:null}
    try {
      const connection=await connectPortal(wc,url,valid,result.requests)
      if(signature(connection)!==plan.signature || connection.access.centre!==plan.centre) throw new PortalError('La sessió o el centre ha canviat. Torna a preparar la factura.')
      const read = async(invoice:PocInvoice):Promise<PocCreated|null> => {
        const found=rows(await connection.request('POST','/factura/cerca/filtre',invoiceFilter(plan.budgetId,invoice.identificadorDocProveidor))).filter(r=>r.identificadorDocProveidor===invoice.identificadorDocProveidor)
        if(!found.length) return null
        if(found.length!==1) throw new PortalError('Hi ha més d’una factura amb aquest número. Cal revisar el resultat.')
        const r=found[0],detail=await connection.request('GET',`/factura/${r.id}`) as Row
        if(detail.pressupost?.id!==plan.budgetId || detail.proveidor?.id!==invoice.proveidor.id || Math.round(detail.importTotalFinal*100)!==Math.round(invoice.importTotalFinal*100)) throw new PortalError('La factura rellegida no coincideix amb la revisió.')
        return {id:r.id,code:String(r.codiGeneratSistema),number:invoice.identificadorDocProveidor,amount:Number(detail.importTotalFinal),supplierId:invoice.proveidor.id}
      }
      for(const invoice of plan.invoices) {
        let record=await read(invoice)
        if(!record) {
          const validation=await connection.request('PUT','/factura/validate',invoice)
          if(!validation || typeof validation!=='object' || Object.keys(validation).length) throw new PortalError(`Esfer@ no valida la factura: ${JSON.stringify(validation).slice(0,2000)}`)
          try { await connection.request('PUT','/factura/desa',invoice) }
          catch(error) { record=await read(invoice); if(!record) throw error }
          record??=await read(invoice)
          if(!record) throw new PortalError('No s’ha pogut confirmar el desament. No es repeteix automàticament; comprova el portal abans de reintentar.')
        }
        result.records.push(record)
      }
      await connection.assertContext()
    } catch(error) { result.error=error instanceof PortalError?error.message:'No es pot completar el desament. Revisa la sessió i comprova el resultat al portal.' }
    return result
  }
}
