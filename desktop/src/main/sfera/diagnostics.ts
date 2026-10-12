import type { WebContents } from 'electron'
import type { DiagnosticCheck, DiagnosticReport } from '../../../../frontend/src/sfera/export-bridge'
import type { InvoiceWriteTrace } from '../../../../frontend/src/sfera/invoice-bridge'
import type { HubClient } from './export-runner'
import { connectPortal, PortalError } from './portal'

/**
 * Read-only readiness check of the open portal session for exporting supplier
 * invoices: every lesson that cost a failed write is checked here first. It
 * makes GETs and the invoice search only; the Hub preflight keeps nothing.
 */
type Row = Record<string, any>

export async function diagnoseExport(wc: WebContents, url: string, valid: () => boolean, hub: HubClient, today = new Date()): Promise<DiagnosticReport> {
  const requests: InvoiceWriteTrace[] = []
  const checks: DiagnosticCheck[] = []
  const add = (id: string, label: string, status: DiagnosticCheck['status'], detail: string) => checks.push({ id, label, status, detail })
  const year = today.getFullYear()
  const connection = await connectPortal(wc, url, valid, requests)
  add('session', 'Sessió i entorn', 'ok', `Centre ${connection.access.centre} al portal de formació.`)
  const safe = async <T>(label: string, read: () => Promise<T>): Promise<T | null> => {
    try { return await read() } catch (error) { add(label, label, 'fail', error instanceof PortalError ? error.message : 'Lectura fallida.'); return null }
  }
  const rows = (value: unknown) => Array.isArray(value) ? value as Row[] : []

  const budgets = rows(await safe('Pressupostos', () => connection.request('GET', '/pressupost/centre')))
  const budget = budgets.find(b => b.any === year && b.tipusPressupost === 'G' && ['A', 'P'].includes(b.estat)) ?? budgets.find(b => b.any === year && ['A', 'P'].includes(b.estat))
  if (budget) add('budget', 'Pressupost editable', 'ok', `Pressupost ${budget.id} de ${year} (${budget.tipusPressupost === 'G' ? 'general' : budget.tipusPressupost}, estat ${budget.estat}).`)
  else add('budget', 'Pressupost editable', 'fail', `No hi ha cap pressupost obert o provisional de ${year}.`)

  const vat = await safe('IVA', () => connection.request('GET', `/parametresCentre/liquidacioIVA?exercici=${year}`)) as Row | null
  if (vat) add('vat', 'Liquidació d’IVA', vat.valor === 'T' ? 'fail' : 'ok', vat.valor === 'T' ? 'El centre liquida IVA: l’exportació encara no ho admet.' : 'El centre no liquida IVA.')

  let partida: Row | undefined
  if (budget) {
    const partidas = rows(await safe('Partides', () => connection.request('GET', `/partidaPressupost/cerca/filtre/${budget.id}/DESPESA`)))
    const usable = partidas.filter(p => rows(p.centreCostDesglosPartida).length === 1)
    partida = usable[0]
    const missing = partidas.length - usable.length
    add('cost-centres', 'Centres de cost de les partides', !partidas.length ? 'fail' : missing ? 'warn' : 'ok',
      !partidas.length ? 'No s’han pogut llegir les partides de despesa.' : `${usable.length} de ${partidas.length} partides tenen un únic centre de cost${missing ? `; ${missing} no es poden exportar fins que es resolgui el centre de cost` : ''}.`)
  }

  const banks = rows(await safe('Bancs', () => connection.request('GET', `/compteBancari/comptesActiuVigent?exercici=${year}&actiu=A`)))
  add('banks', 'Comptes bancaris', banks.length ? 'ok' : 'fail', banks.length ? `${banks.length} comptes actius.` : 'No hi ha cap compte bancari actiu.')
  const suppliers = rows(await safe('Proveïdors', () => connection.request('GET', '/proveidor/cerca'))).filter(s => s.estat === 'A')
  add('suppliers', 'Proveïdors actius', suppliers.length ? 'ok' : 'warn', `${suppliers.length} proveïdors actius.`)

  if (budget) {
    const search = await safe('Cerca de factures', () => connection.request('POST', '/factura/cerca/filtre', { proveidor: '', numFactura: null, partidaSubpartidaExtrapressupostari: null, reserva: '', numDocIntern: null, numDocReferencia: null, dataVencimentDesde: null, dataVencimentFinsa: null, dataRegistreDesde: `${year}/01/01`, dataRegistreFinsa: `${year}/12/31`, descripcio: null, despesaSimplificada: 'F', idPressupost: budget.id }))
    if (Array.isArray(search)) {
      const longest = Math.max(0, ...search.map((r: Row) => String(r.identificadorDocProveidor ?? '').length))
      add('search', 'Cerca de duplicats', 'ok', `${search.length} factures de ${year}; el número més llarg té ${longest} caràcters (límit 20).`)
    } else if (search !== null) add('search', 'Cerca de duplicats', 'fail', 'Format de resposta inesperat.')
  }

  let capabilities: Row[] = []
  try { capabilities = rows(await hub.get('/sfera/capabilities')) } catch { add('hub', 'Hub', 'fail', 'El Hub no exposa l’exportació a Esfer@ (cal una versió més nova).') }
  const verified = capabilities.find(c => c.environment === 'training' && c.status === 'verified')
  if (capabilities.length) add('hub', 'Capacitat al Hub', verified ? 'ok' : 'fail', verified ? `Verificada el ${verified.verified_on}: ${verified.scope}` : 'Cap capacitat verificada per a formació.')

  // A synthetic invoice from the live catalog through the Hub preflight: nothing is kept or written.
  let preflight: DiagnosticReport['preflight'] = null
  const supplier = suppliers[0], bank = banks[0]
  if (verified && budget && partida && supplier && bank && vat?.valor !== 'T') {
    const iso = today.toISOString().slice(0, 10)
    const sample = {
      context: { environment: 'training', centre_code: connection.access.centre, remote_centre_id: budget.idCentre, remote_budget_id: budget.id, financial_year: year, vat_settlement: false },
      invoices: [{ source_ref: 'DIAGNOSTIC', supplier_remote_id: supplier.id, document_number: 'CSC-DIAG-0001', document_date: iso, accounting_date: iso, description: 'Diagnòstic de Cosecre', total: '1.00',
        lines: [{ partida_remote_id: partida.id, cost_centre_remote_id: rows(partida.centreCostDesglosPartida)[0].id, base: '1.00', vat_amount: '0.00' }],
        due_dates: [{ date: iso, amount: '1.00', payment_type: 'TR', bank_account_remote_id: bank.id }] }],
    }
    try {
      const [result] = rows(await hub.post('/sfera/preflight', sample))
      const blocking = rows(result?.problems).filter(p => p.blocking)
      preflight = { state: String(result?.state ?? 'unknown'), problems: blocking.map(p => String(p.message)) }
      add('preflight', 'Factura de prova (sense desar)', blocking.length ? 'fail' : 'ok', blocking.length ? blocking.map(p => p.message).join(' ') : 'Una factura amb aquest catàleg passaria les comprovacions del Hub.')
    } catch (error) { add('preflight', 'Factura de prova (sense desar)', 'fail', error instanceof PortalError ? error.message : 'El Hub no ha respost.') }
  }
  return { centre: connection.access.centre, checkedAt: new Date().toISOString(), ready: checks.every(c => c.status !== 'fail'), checks, preflight, requests }
}

