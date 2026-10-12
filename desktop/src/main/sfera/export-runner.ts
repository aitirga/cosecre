import type { WebContents } from 'electron'
import type { ExportRunResult } from '../../../../frontend/src/sfera/export-bridge'
import type { InvoiceWriteTrace } from '../../../../frontend/src/sfera/invoice-bridge'
import { connectPortal, PortalError, type PortalConnection } from './portal'

/**
 * Runs one approved item of a Hub export plan against the portal session.
 *
 * The renderer names the item; the payload comes from the Hub, where it was
 * validated and approved under a hash. Before any write the plan's context is
 * checked against the live session (centre, budget, year). Once claimed, every
 * exit reports back, and a failure is only ``failed`` when a read showed that
 * nothing was written; otherwise it is ``uncertain`` and must be reconciled.
 */
type Row = Record<string, any>
interface Claim { plan_id: string; item_id: number; attempt_id: number; payload: Row; duplicate_key: string; context: Row }
export interface HubClient { get(path: string): Promise<unknown>; post(path: string, body?: unknown): Promise<unknown> }
interface Report { outcome: 'succeeded' | 'uncertain' | 'failed'; remote_id?: number; remote_code?: string; readback?: Row; http_status?: number; error?: string; no_effect_confirmed?: boolean }

const LIMITS: [string, number][] = [['identificadorDocProveidor', 20], ['identificadorDocCentre', 20], ['descripcio', 100], ['observacions', 500]]
const PLAN_ID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/

export function hubClient(root: string, token: string): HubClient {
  const call = async (method: 'GET' | 'POST', path: string, body?: unknown) => {
    const response = await fetch(root + path, { method, headers: { Authorization: `Bearer ${token}`, ...(body === undefined ? {} : { 'Content-Type': 'application/json' }) }, ...(body === undefined ? {} : { body: JSON.stringify(body) }), redirect: 'error', signal: AbortSignal.timeout(20000) })
    const data = await response.json().catch(() => null) as { detail?: unknown } | null
    if (!response.ok) throw new PortalError(`El Hub ha rebutjat l’operació (${response.status}): ${typeof data?.detail === 'string' ? data.detail : 'sense detall'}`)
    return data
  }
  return { get: path => call('GET', path), post: (path, body) => call('POST', path, body) }
}

/** Reasons the Hub's payload does not fit this session; none means safe to write. */
function contextProblems(claim: Claim, centre: string, budgets: Row[]): string[] {
  const { context, payload } = claim, problems: string[] = []
  if (context.environment !== 'training') problems.push('Aquest runner només escriu al portal de formació.')
  if (context.centre_code !== centre) problems.push(`El pla és del centre ${context.centre_code} i la sessió és del ${centre}.`)
  const budget = budgets.find(b => b.id === context.remote_budget_id)
  if (!budget) problems.push('El pressupost del pla no és del centre de la sessió.')
  else {
    if (budget.idCentre !== context.remote_centre_id) problems.push('El centre del pressupost no coincideix amb el pla.')
    if (budget.any !== context.financial_year) problems.push('L’exercici del pressupost no coincideix amb el pla.')
    if (!['A', 'P'].includes(budget.estat)) problems.push('El pressupost no és editable.')
  }
  const p = payload.pressupost ?? {}
  if (p.id !== context.remote_budget_id || p.any !== context.financial_year || p.idCentre !== context.remote_centre_id) problems.push('La factura no apunta al pressupost del pla.')
  for (const [field, max] of LIMITS) if (String(payload[field] ?? '').length > max) problems.push(`${field} supera ${max} caràcters.`)
  if (!Array.isArray(payload.partidasFactura) || !payload.partidasFactura.length || payload.partidasFactura.some((l: Row) => !Number.isSafeInteger(l?.centreCost?.id))) problems.push('Hi ha línies sense centre de cost.')
  if (payload.liquidat !== 'F' || 'id' in payload || !Array.isArray(payload.vencimentsFactura) || payload.vencimentsFactura.some((v: Row) => v?.liquidat !== 'F' || v?.anulat !== 'F')) problems.push('Només s’admeten altes de factures pendents.')
  return problems
}

const filter = (budgetId: number, year: number, number: string) => ({ proveidor: '', numFactura: number, partidaSubpartidaExtrapressupostari: null, reserva: '', numDocIntern: null, numDocReferencia: null, dataVencimentDesde: null, dataVencimentFinsa: null, dataRegistreDesde: `${year}/01/01`, dataRegistreFinsa: `${year}/12/31`, descripcio: null, despesaSimplificada: 'F', idPressupost: budgetId })

/** The saved invoice with this supplier and number, if any; throws if ambiguous. */
async function find(connection: PortalConnection, claim: Claim): Promise<Row | null> {
  const { payload, context } = claim
  const rows = await connection.request('POST', '/factura/cerca/filtre', filter(context.remote_budget_id, context.financial_year, payload.identificadorDocProveidor))
  if (!Array.isArray(rows)) throw new PortalError('El format de la cerca de factures ha canviat.')
  const same = rows.filter((r: Row) => String(r?.identificadorDocProveidor ?? '').trim().toUpperCase() === String(payload.identificadorDocProveidor).trim().toUpperCase())
  const details = []
  for (const row of same) {
    if (!Number.isSafeInteger(row.id)) throw new PortalError('El format de la cerca de factures ha canviat.')
    const detail = await connection.request('GET', `/factura/${row.id}`) as Row
    if (detail?.proveidor?.id === payload.proveidor.id) details.push({ ...detail, codiGeneratSistema: detail.codiGeneratSistema ?? row.codiGeneratSistema })
  }
  if (details.length > 1) throw new PortalError('Hi ha més d’una factura amb aquest proveïdor i número.')
  return details[0] ?? null
}

const readback = (detail: Row) => ({ supplier_remote_id: detail.proveidor?.id, total: Number(detail.importTotalFinal).toFixed(2), remote_budget_id: detail.pressupost?.id, document_number: String(detail.identificadorDocProveidor ?? '') })
const saved = (detail: Row): Report => ({ outcome: 'succeeded', remote_id: detail.id, remote_code: String(detail.codiGeneratSistema ?? ''), readback: readback(detail), http_status: 200 })
const message = (error: unknown) => error instanceof PortalError ? error.message : 'Error inesperat en escriure a Esfer@.'

const ids = (planId: unknown, itemId: unknown) => {
  if (typeof planId !== 'string' || !PLAN_ID.test(planId) || !Number.isSafeInteger(itemId) || (itemId as number) <= 0) throw new PortalError('Element del pla no vàlid.')
  return { planId, itemId: itemId as number }
}

/**
 * Settles an uncertain or conflicting item by reading the portal: found and
 * matching → reconciled; absent → failed (and claimable again). The Hub decides
 * whether the read matches the plan.
 */
export async function reconcileExportItem(wc: WebContents, url: string, valid: () => boolean, hub: HubClient, rawPlan: unknown, rawItem: unknown): Promise<ExportRunResult> {
  const { planId, itemId } = ids(rawPlan, rawItem)
  const requests: InvoiceWriteTrace[] = []
  const connection = await connectPortal(wc, url, valid, requests)
  const plan = await hub.get(`/sfera/export-plans/${planId}`) as { context: Row; items: { id: number; state: string; payload: Row }[] }
  const item = plan.items.find(i => i.id === itemId)
  if (!item) throw new PortalError('Element no trobat al pla.')
  if (!['uncertain', 'conflict'].includes(item.state)) throw new PortalError('Només es concilia un element incert o en conflicte.')
  if (plan.context.centre_code !== connection.access.centre) throw new PortalError(`El pla és del centre ${plan.context.centre_code} i la sessió és del ${connection.access.centre}.`)
  const claim: Claim = { plan_id: planId, item_id: itemId, attempt_id: 0, payload: item.payload, duplicate_key: '', context: plan.context }
  const found = await find(connection, claim)
  try {
    await hub.post(`/sfera/export-plans/${planId}/items/${itemId}/reconcile`, found
      ? { found: true, remote_id: found.id, remote_code: String(found.codiGeneratSistema ?? ''), readback: readback(found) }
      : { found: false })
  } catch (error) {
    return { planId, itemId, outcome: 'uncertain', remoteCode: found ? String(found.codiGeneratSistema ?? '') : null, error: message(error), requests }
  }
  return found
    ? { planId, itemId, outcome: 'succeeded', remoteCode: String(found.codiGeneratSistema ?? ''), error: null, requests }
    : { planId, itemId, outcome: 'failed', remoteCode: null, error: 'No hi és a Esfer@: l’element es pot tornar a executar.', requests }
}

export async function runExportItem(wc: WebContents, url: string, valid: () => boolean, hub: HubClient, rawPlan: unknown, rawItem: unknown): Promise<ExportRunResult> {
  const { planId, itemId } = ids(rawPlan, rawItem)
  const requests: InvoiceWriteTrace[] = []
  const connection = await connectPortal(wc, url, valid, requests)
  const budgets = await connection.request('GET', '/pressupost/centre')
  if (!Array.isArray(budgets)) throw new PortalError('El format dels pressupostos ha canviat.')
  const claim = await hub.post(`/sfera/export-plans/${planId}/items/${itemId}/claim`) as Claim
  let report: Report
  try {
    const problems = contextProblems(claim, connection.access.centre, budgets)
    if (problems.length) report = { outcome: 'failed', no_effect_confirmed: true, error: problems.join(' ') }
    else report = await write(connection, claim)
  } catch (error) {
    // A failure before the save call cannot have written anything; after it, only a read can tell.
    report = { outcome: 'uncertain', error: message(error) }
  }
  let error: string | null = report.outcome === 'succeeded' ? null : report.error ?? null
  try {
    await hub.post(`/sfera/export-plans/${planId}/items/${itemId}/result`, { attempt_id: claim.attempt_id, ...report })
  } catch (hubError) {
    error = `${message(hubError)} L’element queda en execució al Hub: recupera’l i concilia’l abans de reintentar.`
  }
  return { planId, itemId, outcome: report.outcome, remoteCode: report.remote_code ?? null, error, requests }
}

async function write(connection: PortalConnection, claim: Claim): Promise<Report> {
  const existing = await find(connection, claim)
  if (existing) return { outcome: 'uncertain', error: `Ja existeix a Esfer@ (${existing.codiGeneratSistema ?? existing.id}). Concilia-la en lloc de tornar-la a crear.` }
  const validation = await connection.request('PUT', '/factura/validate', claim.payload)
  if (!validation || typeof validation !== 'object' || Object.keys(validation).length) {
    const after = await find(connection, claim)
    if (after) return saved(after)
    return { outcome: 'failed', no_effect_confirmed: true, error: `Esfer@ no valida la factura: ${JSON.stringify(validation).slice(0, 500)}` }
  }
  try {
    await connection.request('PUT', '/factura/desa', claim.payload)
  } catch (error) {
    const after = await find(connection, claim)
    if (after) return saved(after)
    return { outcome: 'failed', no_effect_confirmed: true, error: message(error) }
  }
  const after = await find(connection, claim)
  return after ? saved(after) : { outcome: 'uncertain', error: 'Esfer@ ha acceptat el desament però la factura no apareix en rellegir-la.' }
}
