/** The PoC uses the invoice DTO observed in Sfer@, with a local HTTP-shaped adapter. */
export interface PocMovement { id: string; date: string; description: string; amount: number; supplierId: number; partidaId: number }
export interface PocInvoice {
  rapel: false; dataDocument: string; dataRegistre: string; descripcio: string; observacions: string
  despesaSimplificada: 'F'; identificadorDocCentre: string; identificadorDocProveidor: string
  importIrpf: number; importIvaTotal: number; importPendent: number; importTotalFinal: number
  tipusDespesa: '1'; tipusDocument: 'F'; pressupost: { id: number; any: number; idCentre: number }
  proveidor: { id: number }; liquidat: 'F'
  partidasFactura: { partidaPressupost: { id: number }; centreCost?: { id: number }; importBase: number; importIrpf: string; importBaseProrrata: number; reservaDespesa: null }[]
  vencimentsFactura: { anulat: 'F'; liquidat: 'F'; dataVenciment: string; import_: number; tipusPagament: 'TR'; compteBancari: { id: number }; descripcio: string }[]
}
export interface PocCreated { id: number; code: string; number: string; amount: number; supplierId: number }
export interface PocTrace { method: 'GET' | 'PUT'; path: string; status: number; durationMs: number; message: string }
export const POC_CATALOG = {
  centre: { id: 900, code: '00000000', name: 'Centre fictici de Cosecre' },
  budget: { id: 901, year: 2026, name: '2026 · General · Prova' },
  suppliers: [{ id: 1001, name: 'Proveïdor fictici A' }, { id: 1002, name: 'Proveïdor fictici B' }],
  partidas: [{ id: 2001, name: 'Material d’oficina · fictícia' }, { id: 2002, name: 'Serveis · fictícia' }],
  bank: { id: 3001, name: 'Banc fictici · sense compte real' },
} as const
const cents = (v: number) => Math.round(v * 100)
/** Esfer@ column limits (the invoice form's maxlength). Longer values pass
 *  /factura/validate but make /factura/desa fail with a generic 405. */
export const SFERA_LIMITS = { identificadorDocProveidor: 20, identificadorDocCentre: 20, descripcio: 100, observacions: 500, vencimentDescripcio: 200 } as const
export function sferaLimitErrors(invoice: PocInvoice): string[] {
  const over = (label: string, value: string | null | undefined, max: number) => (value ?? '').length > max ? [`${label}: ${(value ?? '').length} caràcters (màxim ${max}).`] : []
  return [
    ...over('Número de factura', invoice.identificadorDocProveidor, SFERA_LIMITS.identificadorDocProveidor),
    ...over('Número intern', invoice.identificadorDocCentre, SFERA_LIMITS.identificadorDocCentre),
    ...over('Descripció', invoice.descripcio, SFERA_LIMITS.descripcio),
    ...over('Observacions', invoice.observacions, SFERA_LIMITS.observacions),
    ...invoice.vencimentsFactura.flatMap(v => over('Descripció del venciment', v.descripcio, SFERA_LIMITS.vencimentDescripcio)),
  ]
}
const sferaDate = (iso: string) => iso.split('-').reverse().join('/')
function validDate(iso: string): boolean {
  return /^2026-\d{2}-\d{2}$/.test(iso) && !Number.isNaN(Date.parse(iso)) && new Date(iso).toISOString().slice(0,10) === iso
}
export function generatePocMovements(): PocMovement[] {
  return [
    { id: 'M001', date: '2026-10-12', description: 'COSECRE POC · material d’oficina fictici', amount: -121, supplierId: 1001, partidaId: 2001 },
    { id: 'M002', date: '2026-10-12', description: 'COSECRE POC · servei fictici', amount: -39.95, supplierId: 1002, partidaId: 2002 },
    { id: 'M003', date: '2026-10-12', description: 'COSECRE POC · ingrés fictici', amount: 250, supplierId: 1001, partidaId: 2001 },
  ]
}
export function preparePocInvoices(movements: PocMovement[]): { invoices: PocInvoice[]; excluded: string[] } {
  const invoices: PocInvoice[] = [], excluded: string[] = [], ids = new Set<string>()
  for (const m of movements) {
    if (!/^M\d{3}$/.test(m.id) || ids.has(m.id) || !validDate(m.date) || !m.description.trim() || !Number.isFinite(m.amount) || cents(m.amount) === 0 || Math.abs(m.amount * 100 - cents(m.amount)) > 0.000001) throw new Error(`El moviment ${m.id} té dades incompletes o no vàlides.`)
    ids.add(m.id)
    if (m.amount > 0) { excluded.push(m.id); continue }
    if (Math.abs(m.amount) > 200) throw new Error('La prova admet despeses de fins a 200 € per moviment.')
    if (!POC_CATALOG.suppliers.some(s => s.id === m.supplierId) || !POC_CATALOG.partidas.some(p => p.id === m.partidaId)) throw new Error('Selecciona un proveïdor i una partida del catàleg fictici.')
    const total = cents(Math.abs(m.amount)) / 100
    const number = `CSC-POC-2026-${m.id}`
    invoices.push({
      rapel: false, dataDocument: sferaDate(m.date), dataRegistre: sferaDate(m.date), descripcio: `COSECRE POC · ${m.description.replace(/^COSECRE POC\s*·?\s*/,'')}`.slice(0, SFERA_LIMITS.descripcio), observacions: 'DADES FICTÍCIES. Prova d’extracte a factura. No és un document comptable real.',
      despesaSimplificada: 'F', identificadorDocCentre: `POC-${m.id}`, identificadorDocProveidor: number,
      importIrpf: 0, importIvaTotal: 0, importPendent: total, importTotalFinal: total, tipusDespesa: '1', tipusDocument: 'F',
      pressupost: { id: POC_CATALOG.budget.id, any: POC_CATALOG.budget.year, idCentre: POC_CATALOG.centre.id }, proveidor: { id: m.supplierId }, liquidat: 'F',
      partidasFactura: [{ partidaPressupost: { id: m.partidaId }, importBase: total, importIrpf: '0.00', importBaseProrrata: total, reservaDespesa: null }],
      vencimentsFactura: [{ anulat: 'F', liquidat: 'F', dataVenciment: sferaDate(m.date), import_: total, tipusPagament: 'TR', compteBancari: { id: POC_CATALOG.bank.id }, descripcio: `COSECRE POC · venciment ${m.id}` }],
    })
  }
  if (!invoices.length) throw new Error('Cal almenys un moviment de despesa per preparar una factura.')
  return { invoices, excluded }
}
export interface PocInvoiceTransport {
  request(method: 'GET' | 'PUT', path: string, payload?: PocInvoice): Promise<{ status: number; data: unknown }>
}
/** Stateful simulator: validates payloads, rejects duplicate invoices and reads saved records back. */
export class SyntheticSferaTransport implements PocInvoiceTransport {
  private records = new Map<string,PocCreated>()
  async request(method: 'GET' | 'PUT', path: string, invoice?: PocInvoice) {
    if (method === 'GET' && path === '/services/factura/poc/creades') return { status: 200, data: [...this.records.values()] }
    if (method !== 'PUT' || !['/services/factura/validate','/services/factura/desa'].includes(path) || !invoice) return { status: 405, data: { error: 'Operació no admesa al simulador.' } }
    const errors: string[] = []
    if ('id' in invoice || invoice.importTotalFinal <= 0 || invoice.importTotalFinal > 200) errors.push('Només s’admeten altes de prova positives de fins a 200 €.')
    errors.push(...sferaLimitErrors(invoice))
    if (!invoice.identificadorDocProveidor.startsWith('CSC-POC-') || !invoice.descripcio.startsWith('COSECRE POC') || invoice.pressupost.id !== POC_CATALOG.budget.id || invoice.pressupost.idCentre !== POC_CATALOG.centre.id) errors.push('Context de prova no vàlid.')
    if (!POC_CATALOG.suppliers.some(s => s.id === invoice.proveidor.id) || !POC_CATALOG.partidas.some(p => p.id === invoice.partidasFactura[0]?.partidaPressupost.id)) errors.push('Proveïdor o partida no vàlids.')
    if (cents(invoice.partidasFactura.reduce((sum,line) => sum + line.importBase - Number(line.importIrpf),invoice.importIvaTotal)) !== cents(invoice.importTotalFinal)) errors.push('Les línies no coincideixen amb l’import total.')
    if (cents(invoice.vencimentsFactura.reduce((sum,line) => sum + line.import_,0)) !== cents(invoice.importTotalFinal)) errors.push('Els venciments no coincideixen amb l’import total.')
    if (invoice.liquidat !== 'F' || invoice.vencimentsFactura.some(v => v.liquidat !== 'F' || v.anulat !== 'F' || v.compteBancari.id !== POC_CATALOG.bank.id)) errors.push('La prova només crea factures pendents al banc fictici.')
    if (errors.length) return { status: 422, data: { errors } }
    if (path.endsWith('/validate')) return { status: 200, data: {} }
    if (this.records.has(invoice.identificadorDocProveidor)) return { status: 409, data: { error: 'Aquesta factura de prova ja existeix.' } }
    const saved: PocCreated = { id: 5001 + this.records.size, code: `FC-POC-${String(this.records.size + 1).padStart(4,'0')}`, number: invoice.identificadorDocProveidor, amount: invoice.importTotalFinal, supplierId: invoice.proveidor.id }
    this.records.set(saved.number,saved)
    return { status: 200, data: saved }
  }
}
export async function executePocInvoices(transport: PocInvoiceTransport, invoices: PocInvoice[], trace: (entry: PocTrace) => void): Promise<PocCreated[]> {
  async function request(method: 'GET' | 'PUT', path: string, payload?: PocInvoice) {
    const start = performance.now()
    const response = await transport.request(method,path,payload)
    trace({ method, path, status: response.status, durationMs: Math.round((performance.now() - start) * 100) / 100, message: payload?.identificadorDocProveidor ?? 'Relectura de factures creades' })
    return response
  }
  const before = await request('GET','/services/factura/poc/creades')
  const existing = before.data as PocCreated[]
  for (const invoice of invoices) {
    if (existing.some(r => r.number === invoice.identificadorDocProveidor)) { trace({ method: 'GET', path: '/services/factura/poc/creades', status: 200, durationMs: 0, message: `${invoice.identificadorDocProveidor} · ja creada, no es duplica` }); continue }
    const validation = await request('PUT','/services/factura/validate',invoice)
    if (validation.status !== 200 || Object.keys(validation.data as object).length) throw new Error(`No s’ha validat ${invoice.identificadorDocProveidor}. ${JSON.stringify(validation.data)}`)
    const saved = await request('PUT','/services/factura/desa',invoice)
    if (saved.status !== 200) throw new Error(`No s’ha desat ${invoice.identificadorDocProveidor}. ${JSON.stringify(saved.data)}`)
  }
  const after = await request('GET','/services/factura/poc/creades')
  const records = after.data as PocCreated[]
  if (invoices.some(invoice => !records.some(r => r.number === invoice.identificadorDocProveidor && cents(r.amount) === cents(invoice.importTotalFinal)))) throw new Error('La relectura no coincideix amb les factures preparades.')
  return records
}
