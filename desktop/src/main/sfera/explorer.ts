import type { WebContents } from 'electron'
import type { SferaCell, SferaDataBridge, SferaQueryResult, SferaRequestTrace } from '../../../../frontend/src/sfera/contract'

const ORIGIN = 'https://formacio.bfgh.aplicacions.ensenyament.gencat.cat'
const BASE = '/bfgh/AppJava/bfgh_gesteco/services'
const MAX_ROWS = 10000
const MAX_BYTES = 12 * 1024 * 1024
const HEADER_KEYS = ['TOKEN', 'USR_CENTRE', 'USR_ROL', 'USR_USERNAME_AWA', 'USR_NOM_AWA', 'USR_COGNOM1_AWA', 'USR_COGNOM2_AWA', 'FUNCIONALITAT-ORIGEN', 'PESTANYA-ORIGEN', 'Cache-Control', 'Pragma', 'If-Modified-Since']
// This fixed adapter reads only the portal's own access context; it never leaves main.
const ACCESS_SCRIPT = `(() => {
  const client = window.AppClient;
  const http = window.angular?.element(document.body).injector()?.get('$http');
  const source = http?.defaults.headers.common;
  const centre = client?.CENTRE_SESSIO?.codiExtern;
  if (!source || !centre || !source.TOKEN) return null;
  return { centre: String(centre), headers: Object.fromEntries(${JSON.stringify(HEADER_KEYS)}.filter(k => typeof source[k] === 'string' || (typeof source[k] === 'number' && Number.isFinite(source[k]))).map(k => [k, String(source[k])])) };
})()`
type Access = { centre: string; headers: Record<string, string> }
type Row = Record<string, unknown>
class SferaReadError extends Error {}
const cell = (v: unknown): SferaCell => typeof v === 'number' && Number.isFinite(v) ? v : typeof v === 'boolean' ? v : typeof v === 'string' ? v.slice(0,2000) : null
const pick = (row: Row, keys: string[]): Record<string, SferaCell> => Object.fromEntries(keys.map(k => [k, cell(row[k])]))
const date = (v: unknown): SferaCell => typeof v === 'number' && Number.isFinite(v) ? new Intl.DateTimeFormat('sv-SE', { timeZone: 'Europe/Madrid' }).format(new Date(v)) : cell(v)
export function validateQuery(value: unknown): Parameters<SferaDataBridge['query']>[0] {
  if (!value || typeof value !== 'object' || Array.isArray(value)) throw new Error('Consulta no vàlida.')
  const q = value as Record<string, unknown>
  if (Object.keys(q).some(k => !['dataset','budgetId'].includes(k)) || typeof q.dataset !== 'string' || !['budgets','suppliers','invoices'].includes(q.dataset) || (q.budgetId !== undefined && (!Number.isSafeInteger(q.budgetId) || Number(q.budgetId) <= 0))) throw new Error('Consulta no vàlida.')
  return q as unknown as Parameters<SferaDataBridge['query']>[0]
}
export async function queryPortal(wc: WebContents, configuredUrl: string, input: Parameters<SferaDataBridge['query']>[0], contextValid: () => boolean): Promise<SferaQueryResult> {
  const started = performance.now()
  const result: SferaQueryResult = { dataset: input.dataset, centre: '', budgetId: input.budgetId ?? null, budgets: [], rows: [], totalRows: 0, truncated: false, requests: [], durationMs: 0, completedAt: '', error: null }
  const readAccess = async (): Promise<Access> => {
    const configured = new URL(configuredUrl), current = new URL(wc.getURL())
    // The current adapter has been verified only against the training portal.
    if (configured.origin !== ORIGIN || configured.pathname !== '/bfgh/gestioeconomica/') throw new SferaReadError('Aquest portal encara no té un adaptador de dades verificat. Utilitza el navegador.')
    if (!contextValid() || current.origin !== configured.origin || current.pathname !== configured.pathname) throw new SferaReadError('Obre el navegador d’Esfer@ i identifica’t al portal de formació.')
    let timeout: ReturnType<typeof setTimeout> | undefined
    const access = await Promise.race([
      wc.executeJavaScript(ACCESS_SCRIPT) as Promise<Access | null>,
      new Promise<never>((_resolve,reject) => { timeout = setTimeout(() => reject(new SferaReadError('Obre el navegador d’Esfer@ i espera que acabi de carregar el centre.')),10000) }),
    ]).finally(() => clearTimeout(timeout))
    if (!access || !/^\d{8}$/.test(access.centre) || !access.headers.TOKEN || !access.headers.USR_CENTRE) throw new SferaReadError('Identifica’t a Esfer@ i selecciona un centre al navegador abans de consultar les dades.')
    return access
  }
  try {
    const access = await readAccess()
    result.centre = access.centre
    const fetchRows = async (path: string, body?: object): Promise<Row[]> => {
      const trace: SferaRequestTrace = { method: body ? 'POST' : 'GET', path: BASE + path, status: null, durationMs: 0, rows: null }
      result.requests.push(trace)
      const start = performance.now()
      try {
        const response = await wc.session.fetch(ORIGIN + trace.path, { method: trace.method, headers: { ...access.headers, ...(body ? { 'Content-Type': 'application/json' } : {}) }, ...(body ? { body: JSON.stringify(body) } : {}), credentials: 'include', redirect: 'manual', signal: AbortSignal.timeout(20000) })
        trace.status = response.status
        if (!response.ok || !response.headers.get('content-type')?.includes('application/json')) throw new SferaReadError('Esfer@ no ha retornat dades. Revisa la sessió i el centre al navegador.')
        const reader = response.body?.getReader()
        if (!reader) throw new SferaReadError('Esfer@ ha retornat una resposta buida.')
        const chunks: Uint8Array[] = []; let size = 0
        while (true) {
          const { done, value } = await reader.read(); if (done) break
          size += value.byteLength
          if (size > MAX_BYTES) { await reader.cancel(); throw new SferaReadError('La resposta d’Esfer@ supera el límit de lectura (12 MB).') }
          chunks.push(value)
        }
        const data: unknown = JSON.parse(Buffer.concat(chunks).toString('utf8'))
        if (!Array.isArray(data) || data.some(row => !row || typeof row !== 'object' || Array.isArray(row) || !Number.isSafeInteger(row.id) || row.id <= 0)) throw new SferaReadError('El format de les dades d’Esfer@ ha canviat.')
        trace.rows = data.length
        return data as Row[]
      } finally { trace.durationMs = Math.round(performance.now() - start) }
    }
    // Verify the requested budget against this centre, rather than trusting renderer IDs.
    const budgets = await fetchRows('/pressupost/centre')
    if (budgets.some(b => !Number.isInteger(b.any) || typeof b.tipusPressupost !== 'string' || typeof b.estat !== 'string')) throw new SferaReadError('El format de les dades d’Esfer@ ha canviat.')
    result.budgets = budgets.filter(b => Number.isSafeInteger(b.id) && Number.isInteger(b.any)).map(b => ({ id: Number(b.id), year: Number(b.any), label: `${b.any} · ${b.tipusPressupost === 'G' ? 'General' : b.tipusPressupost === 'M' ? 'Menjador' : String(b.tipusPressupost)} · ${b.estat === 'A' ? 'Aprovat' : b.estat === 'T' ? 'Validat i tancat' : String(b.estat)}` }))
    let rows: Row[]
    if (input.dataset === 'budgets') {
      rows = budgets
      result.rows = rows.slice(0,MAX_ROWS).map(r => pick(r, ['id','any','tipusPressupost','estat','totalPressupostatIngres','totalPressupostatDespesa','pendentExecutarIngres','pendentExecutarDespesa','romanentExerciciAnterior','dataAprovacioPressupost','dataEstat']))
    } else if (input.dataset === 'suppliers') {
      rows = await fetchRows('/proveidor/cerca')
      if (rows.some(r => typeof r.nom !== 'string')) throw new SferaReadError('El format de les dades d’Esfer@ ha canviat.')
      result.rows = rows.slice(0,MAX_ROWS).map(r => pick(r, ['id','nifProveidor','nom','nomComercial','nomMunicipi','estat','saldoProveidor','codiCompte']))
    } else {
      const budget = result.budgets.find(b => b.id === input.budgetId)
      if (!budget) throw new SferaReadError('Selecciona un pressupost del centre per consultar-ne les factures.')
      rows = await fetchRows('/factura/cerca/filtre', { proveidor: '', numFactura: null, partidaSubpartidaExtrapressupostari: null, reserva: '', numDocIntern: null, numDocReferencia: null, dataVencimentDesde: null, dataVencimentFinsa: null, dataRegistreDesde: `${budget.year}/01/01`, dataRegistreFinsa: `${budget.year}/12/31`, descripcio: null, despesaSimplificada: 'F', idPressupost: budget.id })
      if (rows.some(r => typeof r.importTotalFinal !== 'number' || !Number.isFinite(r.importTotalFinal))) throw new SferaReadError('El format de les dades d’Esfer@ ha canviat.')
      result.rows = rows.slice(0,MAX_ROWS).map(r => ({ ...pick(r, ['id','codiGeneratSistema','identificadorDocProveidor','identificadorDocCentre','descripcio','importTotalFinal','importEfectuat','importPendent','tipusDocument','anulat','liquidat','numAssentament']), proveidor: cell((r.proveidor as Row | null)?.nom), dataDocument: date(r.dataDocument), dataRegistre: date(r.dataRegistre) }))
    }
    result.totalRows = rows.length; result.truncated = rows.length > MAX_ROWS
    const final = await readAccess()
    if (final.centre !== access.centre || ['TOKEN','USR_CENTRE','USR_ROL','USR_USERNAME_AWA'].some(k => final.headers[k] !== access.headers[k]) || !contextValid()) throw new SferaReadError('La sessió o el centre ha canviat durant la consulta. Torna a executar-la.')
  } catch (error) {
    result.rows = []; result.totalRows = 0; result.budgets = []
    // Never return network exception details, URLs with parameters or access headers.
    result.error = error instanceof SferaReadError ? error.message : 'No es pot completar la consulta. Revisa la connexió i la sessió al navegador.'
  }
  result.durationMs = Math.round(performance.now() - started); result.completedAt = new Date().toISOString()
  return result
}
