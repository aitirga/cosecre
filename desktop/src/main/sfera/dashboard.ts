import type { WebContents } from 'electron'
import type { SferaRequestTrace } from '../../../../frontend/src/sfera/contract'
import type {
  SferaAccount, SferaCentreOption, SferaDashboard, SferaDashboardBudget, SferaDashboardResult,
  SferaIncomeRow, SferaInvoiceRow, SferaLine, SferaMonth, SferaMovement,
} from '../../../../frontend/src/sfera/dashboard'

/**
 * Read-only dashboard over Esfer@'s training portal.
 *
 * Every request is one of a fixed set of reads, verified on 12 October 2026
 * against the portal's own client (v12.40.2_B000). Two of them are POSTs only
 * because the portal searches that way; none writes.
 */
const ORIGIN = 'https://formacio.bfgh.aplicacions.ensenyament.gencat.cat'
const BASE = '/bfgh/AppJava/bfgh_gesteco/services'
const MAX_BYTES = 12 * 1024 * 1024
const HEADER_KEYS = ['TOKEN', 'USR_CENTRE', 'USR_ROL', 'USR_USERNAME_AWA', 'USR_NOM_AWA', 'USR_COGNOM1_AWA', 'USR_COGNOM2_AWA', 'FUNCIONALITAT-ORIGEN', 'PESTANYA-ORIGEN', 'Cache-Control', 'Pragma', 'If-Modified-Since']
// The portal keeps some default headers as functions; they are evaluated, as its own $http does.
const ACCESS_SCRIPT = `(() => {
  const source = window.angular?.element(document.body).injector()?.get('$http')?.defaults.headers.common;
  const centre = window.AppClient?.CENTRE_SESSIO;
  if (!source || !source.TOKEN) return null;
  const value = v => typeof v === 'function' ? v() : v;
  return {
    centre: centre?.codiExtern ? { code: String(centre.codiExtern), name: String(centre.labelCentre ?? centre.label ?? '') } : null,
    headers: Object.fromEntries(${JSON.stringify(HEADER_KEYS)}.map(k => [k, value(source[k])]).filter(([, v]) => typeof v === 'string' || (typeof v === 'number' && Number.isFinite(v))).map(([k, v]) => [k, String(v)])),
  };
})()`
// Esfer@'s «Escolliu el centre» dialog: the rows it offers, and choosing one through its own action.
const CENTRES_SCRIPT = `(() => [...document.querySelectorAll('[data-ng-click="setCentreActiuModal(centre)"]')]
  .map(e => window.angular?.element(e).scope()?.centre).filter(c => c && c.codiExtern)
  .map(c => ({ code: String(c.codiExtern), name: String(c.labelCentre ?? c.label ?? '') })))()`
const selectScript = (code: string) => `(() => {
  const row = [...document.querySelectorAll('[data-ng-click="setCentreActiuModal(centre)"]')].find(e => String(window.angular?.element(e).scope()?.centre?.codiExtern) === ${JSON.stringify(code)});
  const scope = row && window.angular.element(row).scope();
  if (!scope || typeof scope.setCentreActiuModal !== 'function') return false;
  scope.$apply(() => scope.setCentreActiuModal(scope.centre));
  return true;
})()`

type Row = Record<string, unknown>
type Access = { centre: { code: string; name: string } | null; headers: Record<string, string> }
class ReadError extends Error {
  constructor(message: string, readonly centres?: SferaCentreOption[]) { super(message) }
}

const num = (v: unknown): number => typeof v === 'number' && Number.isFinite(v) ? v : 0
const str = (v: unknown): string => typeof v === 'string' ? v.slice(0, 500) : typeof v === 'number' ? String(v) : ''
const round = (v: number) => Math.round(v * 100) / 100
const madrid = new Intl.DateTimeFormat('sv-SE', { timeZone: 'Europe/Madrid' })
const day = (v: unknown): string | null => typeof v === 'number' && Number.isFinite(v) ? madrid.format(new Date(v)) : typeof v === 'string' && /^\d{4}-\d{2}-\d{2}/.test(v) ? v.slice(0, 10) : null
const KIND: Record<string, string> = { G: 'General', M: 'Menjador' }
const STATE: Record<string, string> = { A: 'Aprovat', P: 'Provisional', E: 'En elaboració', T: 'Validat i tancat', L: 'Liquidat' }
// Journal operation types, named after the descriptions esfer@ writes with them.
const OPERATION: Record<string, string> = {
  RF: 'Registre de factura', PF: 'Pagament de factura', AF: 'Devolució de factura',
  DS: 'Despesa simplificada', PDS: 'Pagament de despesa simplificada',
  RI: 'Registre d’ingrés', CI: 'Cobrament d’ingrés', DI: 'Devolució d’ingrés',
  TBX: 'Traspàs entre banc i caixa', TE: 'Obertura d’exercici',
}
const rows = (data: unknown, check: (r: Row) => boolean = () => true): Row[] => {
  if (!Array.isArray(data) || data.some(r => !r || typeof r !== 'object' || Array.isArray(r) || !check(r as Row))) throw new ReadError('El format de les dades d’Esfer@ ha canviat.')
  return data as Row[]
}
const withId = (r: Row) => Number.isSafeInteger(r.id) && Number(r.id) > 0

function budgetOf(b: Row): SferaDashboardBudget {
  const kind = str(b.tipusPressupost), state = str(b.estat)
  return {
    id: Number(b.id), year: Number(b.any), kind, kindLabel: KIND[kind] ?? kind, state, stateLabel: STATE[state] ?? state,
    approvedAt: day(b.dataAprovacioPressupost), changedAt: day(b.dataModificacio ?? b.dataEstat), remnant: num(b.romanentExerciciAnterior),
  }
}

function linesOf(estat: Row): SferaLine[] {
  const read = (list: unknown, kind: 'I' | 'D') => rows(list ?? [], r => typeof r.codiPartida === 'string').map(r => {
    const code = str(r.codiPartida), sub = r.esSubPartida === 'T' && code.includes('.')
    return {
      code, name: str(r.nomPartida), kind, fund: str(r.codFinalista).trim(), parent: sub ? code.slice(0, code.lastIndexOf('.')) : null,
      budgeted: num(r.importPressupostat), imputed: num(r.importImputat), committed: num(r.importCompromes), available: num(r.saldoPartida),
    }
  })
  return [...read(estat.partidaPressupostsIngressos, 'I'), ...read(estat.partidaPressupostsDespeses, 'D')]
}

function accountsOf(banks: Row[], cash: Row[]): SferaAccount[] {
  return [
    ...banks.map(b => ({ code: str(b.codiCompte), name: str(b.nomDescriptiuCompte) || 'Compte bancari', kind: 'bank' as const, balance: num(b.saldo), active: b.estat === 'A', main: b.comptePrincipal === 'T', detail: str(b.numeroCompte).slice(-4) ? `···${str(b.numeroCompte).slice(-4)}` : null })),
    ...cash.map(c => ({ code: str(c.codCompte), name: str(c.descripcio) || 'Caixa', kind: 'cash' as const, balance: num(c.saldo), active: c.activa === 'A', main: false, detail: str(c.responsable) || null })),
  ].filter(a => a.code)
}

/** Months, a daily balance and the latest movements, from the journal's legs on banks and cash boxes. */
function treasuryOf(journal: Row[], accounts: SferaAccount[], year: number, anchored: boolean) {
  const treasury = new Map(accounts.map(a => [a.code, a]))
  const entries = new Map<string, Row[]>()
  for (const r of journal) {
    if (r.anulat === 'T' || !treasury.has(str(r.codiComptePartida))) continue
    const key = str(r.numeroMoviment) + '|' + str(r.tipusOperacio)
    entries.set(key, [...(entries.get(key) ?? []), r])
  }
  const months = new Map<string, SferaMonth>()
  for (let m = 1; m <= 12; m++) { const key = `${year}-${String(m).padStart(2, '0')}`; months.set(key, { month: key, collected: 0, paid: 0 }) }
  const daily = new Map<string, number>()
  const movements: SferaMovement[] = []
  for (const legs of entries.values()) {
    const date = day(legs[0].dataMoviment) ?? day(legs[0].dataRegistre)
    if (!date) continue
    const net = legs.reduce((s, r) => s + num(r.import_), 0)
    daily.set(date, (daily.get(date) ?? 0) + net)
    // Money moved between the centre's own banks and boxes is not income or spending.
    const internal = legs.length > 1 && Math.abs(net) < 0.005
    const month = months.get(date.slice(0, 7))
    if (month && !internal) for (const r of legs) { const v = num(r.import_); if (v > 0) month.collected += v; else month.paid -= v }
    for (const r of legs) {
      const type = str(r.tipusOperacio)
      movements.push({ date, type, typeLabel: OPERATION[type] ?? type, description: str(r.descripcioMoviment).replace(/\s+/g, ' ').trim(), account: treasury.get(str(r.codiComptePartida))!.name, amount: round(num(r.import_)) })
    }
  }
  let series: { date: string; balance: number }[] = []
  if (anchored) {
    // Balances are current; the year's movements, walked back, give the opening and every day after it.
    const total = accounts.reduce((s, a) => s + a.balance, 0)
    const days = [...daily.keys()].sort()
    let balance = total - days.reduce((s, d) => s + daily.get(d)!, 0)
    series = [{ date: `${year}-01-01`, balance: round(balance) }]
    for (const d of days) { balance += daily.get(d)!; series.push({ date: d, balance: round(balance) }) }
  }
  movements.sort((a, b) => b.date.localeCompare(a.date))
  return { months: [...months.values()].map(m => ({ ...m, collected: round(m.collected), paid: round(m.paid) })), series, movements: movements.slice(0, 60) }
}

export async function readDashboard(wc: WebContents, configuredUrl: string, input: { budgetId?: number }, contextValid: () => boolean): Promise<SferaDashboardResult> {
  const started = performance.now()
  const requests: SferaRequestTrace[] = []
  try {
    const access = await readAccess(wc, configuredUrl, contextValid)
    const fetchJson = async (path: string, body?: object): Promise<unknown> => {
      const trace: SferaRequestTrace = { method: body ? 'POST' : 'GET', path: BASE + path.replace(/\?.*$/, ''), status: null, durationMs: 0, rows: null }
      requests.push(trace)
      const start = performance.now()
      try {
        const response = await wc.session.fetch(ORIGIN + BASE + path, { method: trace.method, headers: { ...access.headers, Accept: 'application/json', ...(body ? { 'Content-Type': 'application/json' } : {}) }, ...(body ? { body: JSON.stringify(body) } : {}), credentials: 'include', redirect: 'manual', signal: AbortSignal.timeout(30000) })
        trace.status = response.status
        if (!response.ok || !response.headers.get('content-type')?.includes('application/json')) throw new ReadError('Esfer@ no ha retornat dades. Revisa la sessió i el centre al navegador.')
        const text = await response.text()
        if (Buffer.byteLength(text) > MAX_BYTES) throw new ReadError('La resposta d’Esfer@ supera el límit de lectura (12 MB).')
        const data: unknown = JSON.parse(text)
        trace.rows = Array.isArray(data) ? data.length : null
        return data
      } finally { trace.durationMs = Math.round(performance.now() - start) }
    }
    const budgetRows = rows(await fetchJson('/pressupost/centre'), r => withId(r) && Number.isInteger(r.any) && typeof r.tipusPressupost === 'string')
    if (!budgetRows.length) throw new ReadError('Aquest centre no té cap pressupost a Esfer@.')
    const budgets = budgetRows.map(budgetOf).sort((a, b) => b.year - a.year || a.kind.localeCompare(b.kind))
    const latest = budgets[0].year
    // The renderer's id is only a choice among this centre's budgets.
    const budget = (input.budgetId && budgets.find(b => b.id === input.budgetId)) || budgets.find(b => b.year === latest && b.kind === 'G') || budgets[0]
    const y = budget.year
    const invoiceFilter = { proveidor: '', numFactura: null, partidaSubpartidaExtrapressupostari: null, reserva: '', numDocIntern: null, numDocReferencia: null, dataVencimentDesde: null, dataVencimentFinsa: null, dataRegistreDesde: `${y}/01/01`, dataRegistreFinsa: `${y}/12/31`, descripcio: null, despesaSimplificada: 'F', idPressupost: budget.id }
    const incomeFilter = { aportador: '', numFactura: '', partidaSubpartidaExtrapressupostari: '', numDocIntern: '', numDocReferencia: '', dataVencimentDesde: '', dataVencimentFinsa: '', dataRegistreDesde: `${y}/01/01`, dataRegistreFinsa: `${y}/12/31`, descripcio: '', ingresSimplificat: 'F', idPressupost: budget.id }
    const [estat, banks, cash, journal, invoices, incomes, eInvoices] = await Promise.all([
      fetchJson(`/pressupost/estat/${budget.id}`),
      fetchJson('/compteBancari/findByCentre'),
      fetchJson('/caixaEfectiu/cerca'),
      // The journal covers the whole centre for the dates asked, whichever budget is named.
      fetchJson(`/consulta/ldo?dataInici=01/01/${y}&dataFi=31/12/${y}&idPressupost=${budget.id}`),
      fetchJson('/factura/cerca/filtre', invoiceFilter),
      fetchJson('/ingres/cerca/filtre', incomeFilter),
      fetchJson('/facturaElectronica/pendents'),
    ])
    if (!estat || typeof estat !== 'object' || Array.isArray(estat)) throw new ReadError('El format de les dades d’Esfer@ ha canviat.')
    const e = estat as Row
    const accounts = accountsOf(rows(banks, withId), rows(cash, withId))
    const treasury = treasuryOf(rows(journal, r => typeof r.codiComptePartida === 'string'), accounts, y, y === latest)
    const data: SferaDashboard = {
      centre: access.centre!,
      budgets, budget,
      execution: {
        income: { budgeted: num(e.totalPressupostatIngres), imputed: num(e.totalImputatIngressos), available: num(e.totalDisponibleIngressos) },
        expense: { budgeted: num(e.totalPressupostatDespesa), imputed: num(e.totalImputatDespeses), available: num(e.totalDisponibleDespeses) },
        collections: { total: num(e.totalCobraments), year: num(e.cobramentsAnyPressupost), previous: num(e.cobramentsExercisisAnteriors) },
        payments: { total: num(e.totalPagaments), year: num(e.pagamentsAnyPressupost), previous: num(e.pagamentsExercisisAnteriors) },
        balance: num(e.equilibriPressupost),
      },
      lines: linesOf(e),
      treasury: { accounts, total: round(accounts.reduce((s, a) => s + a.balance, 0)), series: treasury.series, seriesYear: y === latest ? y : null },
      months: treasury.months,
      movements: treasury.movements,
      invoices: rows(invoices, withId).map((r): SferaInvoiceRow => ({ id: Number(r.id), code: str(r.codiGeneratSistema), date: day(r.dataRegistre), supplier: str((r.proveidor as Row | null)?.nom), number: str(r.identificadorDocProveidor), description: str(r.descripcio), total: num(r.importTotalFinal), paid: num(r.importEfectuat), pending: num(r.importPendent), type: str(r.tipusDocument), cancelled: r.anulat === 'T' })),
      incomes: rows(incomes, withId).map((r): SferaIncomeRow => ({ id: Number(r.id), code: str(r.codiGeneratSistema), date: day(r.dataRegistre), contributor: str((r.aportador as Row | null)?.nom), description: str(r.descripcio), total: num(r.importTotalFinal), collected: num(r.importEfectuat), pending: num(r.importPendent), type: str(r.tipusDocument), cancelled: r.anulat === 'T' })),
      eInvoicesPending: Array.isArray(eInvoices) ? eInvoices.length : 0,
      requests, durationMs: 0, completedAt: '',
    }
    // Nothing read counts if the person changed session or centre while it was read.
    const final = await readAccess(wc, configuredUrl, contextValid)
    if (final.centre?.code !== access.centre?.code || ['TOKEN', 'USR_CENTRE', 'USR_ROL', 'USR_USERNAME_AWA'].some(k => final.headers[k] !== access.headers[k])) throw new ReadError('La sessió o el centre ha canviat durant la lectura. Torna-ho a provar.')
    data.durationMs = Math.round(performance.now() - started); data.completedAt = new Date().toISOString()
    return { ok: true, data }
  } catch (error) {
    // Never return network details, URLs with parameters or access headers.
    if (error instanceof ReadError) return { ok: false, error: error.message, ...(error.centres ? { centres: error.centres } : {}) }
    return { ok: false, error: 'No es pot completar la lectura. Revisa la connexió i la sessió al navegador.' }
  }
}

async function readAccess(wc: WebContents, configuredUrl: string, contextValid: () => boolean): Promise<Access> {
  const configured = new URL(configuredUrl), current = new URL(wc.getURL())
  // The adapter has been verified only against the training portal.
  if (configured.origin !== ORIGIN || configured.pathname !== '/bfgh/gestioeconomica/') throw new ReadError('Aquest portal encara no té un adaptador de dades verificat. Utilitza el navegador.')
  if (!contextValid() || current.origin !== configured.origin || current.pathname !== configured.pathname) throw new ReadError('Esfer@ encara s’està obrint. Si no s’identifica sol, obre el navegador i identifica’t.')
  const run = <T>(script: string) => {
    let timeout: ReturnType<typeof setTimeout> | undefined
    return Promise.race([
      wc.executeJavaScript(script) as Promise<T>,
      new Promise<never>((_resolve, reject) => { timeout = setTimeout(() => reject(new ReadError('Esfer@ encara s’està carregant. Torna-ho a provar en uns segons.')), 10000) }),
    ]).finally(() => clearTimeout(timeout))
  }
  const access = await run<Access | null>(ACCESS_SCRIPT)
  if (access?.headers.TOKEN && access.centre && /^\d{8}$/.test(access.centre.code) && access.headers.USR_CENTRE) return access
  // Signed in but no centre yet: the portal issues its token only after one is chosen.
  const centres = (await run<SferaCentreOption[]>(CENTRES_SCRIPT).catch(() => [])).filter(c => /^\d{8}$/.test(c.code))
  if (centres.length) throw new ReadError('Esfer@ espera que triïs un centre.', centres)
  throw new ReadError('Identifica’t a Esfer@ al navegador per veure el tauler.')
}

/** Picks a centre in Esfer@'s dialog, only among those it offers, then reads the dashboard. */
export async function selectCentre(wc: WebContents, configuredUrl: string, code: unknown, contextValid: () => boolean): Promise<SferaDashboardResult> {
  if (typeof code !== 'string' || !/^\d{8}$/.test(code)) return { ok: false, error: 'Centre no vàlid.' }
  try {
    await readAccess(wc, configuredUrl, contextValid)
    return readDashboard(wc, configuredUrl, {}, contextValid)
  } catch (error) {
    if (!(error instanceof ReadError) || !error.centres?.some(c => c.code === code)) return readDashboard(wc, configuredUrl, {}, contextValid)
    if (!await wc.executeJavaScript(selectScript(code))) return { ok: false, error: 'Esfer@ no ha acceptat el centre. Tria’l al navegador.' }
    // The portal loads the centre's session asynchronously.
    const end = Date.now() + 20000
    while (Date.now() < end) {
      await new Promise(done => setTimeout(done, 400))
      if (!contextValid()) break
      const access = await wc.executeJavaScript(ACCESS_SCRIPT).catch(() => null) as Access | null
      if (access?.centre?.code === code && access.headers.USR_CENTRE) return readDashboard(wc, configuredUrl, {}, contextValid)
    }
    return { ok: false, error: 'Esfer@ no ha carregat el centre a temps. Torna-ho a provar.' }
  }
}
