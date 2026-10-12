import type { PocMovement, PocInvoice, PocCreated } from './invoice-poc'

export interface InvoiceChoice { id: number; label: string }
export interface InvoiceCatalog {
  centre: string
  budgets: InvoiceChoice[]
  budgetId: number
  suppliers: InvoiceChoice[]
  partidas: InvoiceChoice[]
  banks: InvoiceChoice[]
}
export interface InvoicePlan {
  id: string
  centre: string
  budget: string
  bank: string
  invoices: PocInvoice[]
  suppliers: InvoiceChoice[]
}
export interface InvoiceWriteTrace { method: 'GET' | 'POST' | 'PUT'; path: string; status: number | null; durationMs: number; error?: string }
export interface InvoiceCommitResult { records: PocCreated[]; requests: InvoiceWriteTrace[]; error: string | null }
export interface SferaInvoiceBridge {
  catalog(budgetId?: number): Promise<InvoiceCatalog>
  prepare(input: { budgetId: number; bankId: number; movements: PocMovement[] }): Promise<InvoicePlan>
  /** Main uses the reviewed plan it owns. It does not accept a write payload. */
  create(planId: string): Promise<InvoiceCommitResult>
}
