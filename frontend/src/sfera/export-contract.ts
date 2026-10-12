import type { InvoicePlan } from './invoice-bridge'

/** Hub export plans (``/api/v1/sfera``): Cosecre's own contract, amounts as decimal strings. */
export interface ExportContext {
  environment: 'training' | 'production'
  centre_code: string
  remote_centre_id: number
  remote_budget_id: number
  financial_year: number
  vat_settlement: boolean
}
export interface ExportLine { partida_remote_id: number; cost_centre_remote_id: number | null; base: string; vat_amount: string | null; withholding_amount?: string }
export interface ExportDueDate { date: string; amount: string; payment_type: string; bank_account_remote_id: number | null; description?: string | null }
export interface ExportInvoice {
  source_ref: string
  document_id?: number | null
  movement_id?: number | null
  supplier_remote_id: number
  document_number: string
  internal_number?: string | null
  document_date: string
  accounting_date: string
  description: string
  observations?: string | null
  total: string
  lines: ExportLine[]
  due_dates: ExportDueDate[]
}
export interface ExportProblem { field: string; code: string; message: string; blocking: boolean }
export interface ExportAttempt { id: number; outcome: string; http_status: number | null; remote_id: number | null; error: string | null; started_at: string; finished_at: string | null }
export interface ExportItem {
  id: number; source_ref: string; document_id: number | null; movement_id: number | null; duplicate_key: string
  state: string; problems: ExportProblem[]; invoice: ExportInvoice; payload: Record<string, unknown>
  remote_id: number | null; remote_code: string | null; attempts: ExportAttempt[]
}
export interface ExportPlan { id: string; state: string; plan_hash: string; context: ExportContext; created_at: string; approved_at: string | null; items: ExportItem[] }
export interface ExportPlanSummary { id: string; state: string; environment: string; centre_code: string; items: number; created_at: string }
export interface PreflightResult { source_ref: string; duplicate_key: string; state: string; problems: ExportProblem[]; payload: Record<string, unknown> }
export interface Capability { entity: string; action: string; environment: string; status: string; verified_on: string | null; scope: string }

/** ``DD/MM/YYYY`` (the portal's) → ``YYYY-MM-DD``. */
export function isoDate(value: string): string {
  const match = /^(\d{2})\/(\d{2})\/(\d{4})$/.exec(value)
  if (!match) throw new Error(`Data no vàlida: ${value}`)
  return `${match[3]}-${match[2]}-${match[1]}`
}
const amount = (value: number) => (Math.round(value * 100) / 100).toFixed(2)

/**
 * A reviewed extract-test plan (real portal IDs, prepared by the desktop app)
 * as a Hub export plan. Nothing is inferred: every remote ID comes from the
 * plan the main process built against the live catalog.
 */
export function contractFromPocPlan(plan: InvoicePlan): { context: ExportContext; invoices: ExportInvoice[] } {
  const first = plan.invoices[0]
  if (!first) throw new Error('El pla no té factures.')
  const context: ExportContext = {
    environment: 'training', centre_code: plan.centre, remote_centre_id: first.pressupost.idCentre,
    remote_budget_id: first.pressupost.id, financial_year: first.pressupost.any,
    // The desktop app refuses to prepare for a centre that settles VAT.
    vat_settlement: false,
  }
  const invoices = plan.invoices.map((invoice): ExportInvoice => {
    if (invoice.pressupost.id !== context.remote_budget_id) throw new Error('Totes les factures han de ser del mateix pressupost.')
    return {
      source_ref: invoice.identificadorDocCentre,
      supplier_remote_id: invoice.proveidor.id,
      document_number: invoice.identificadorDocProveidor,
      internal_number: invoice.identificadorDocCentre,
      document_date: isoDate(invoice.dataDocument),
      accounting_date: isoDate(invoice.dataRegistre),
      description: invoice.descripcio,
      observations: invoice.observacions,
      total: amount(invoice.importTotalFinal),
      lines: invoice.partidasFactura.map(line => ({
        partida_remote_id: line.partidaPressupost.id, cost_centre_remote_id: line.centreCost?.id ?? null,
        base: amount(line.importBase), vat_amount: '0.00', withholding_amount: amount(Number(line.importIrpf)),
      })),
      due_dates: invoice.vencimentsFactura.map(due => ({
        date: isoDate(due.dataVenciment), amount: amount(due.import_), payment_type: due.tipusPagament,
        bank_account_remote_id: due.compteBancari.id, description: due.descripcio,
      })),
    }
  })
  return { context, invoices }
}

export const STATE_LABELS: Record<string, string> = {
  blocked: 'Bloquejat', ready: 'A punt', approved: 'Aprovat', executing: 'En execució', succeeded: 'Desat',
  uncertain: 'Incert', reconciled: 'Conciliat', conflict: 'Conflicte', failed: 'Fallat', cancelled: 'Cancel·lat', finished: 'Finalitzat',
}
