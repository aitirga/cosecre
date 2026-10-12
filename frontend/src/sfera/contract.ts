/** Fixed read capabilities. No URLs, credentials, scripts or write payloads cross this bridge. */
export type SferaDataset = 'budgets' | 'suppliers' | 'invoices'
export type SferaCell = string | number | boolean | null
export interface SferaBudget { id: number; year: number; label: string }
export interface SferaRequestTrace {
  method: 'GET' | 'POST'
  path: string
  status: number | null
  durationMs: number
  rows: number | null
}
export interface SferaQueryResult {
  dataset: SferaDataset
  centre: string
  budgetId: number | null
  budgets: SferaBudget[]
  rows: Record<string, SferaCell>[]
  totalRows: number
  truncated: boolean
  requests: SferaRequestTrace[]
  durationMs: number
  completedAt: string
  error: string | null
}
export interface SferaDataBridge {
  query(input: { dataset: SferaDataset; budgetId?: number }): Promise<SferaQueryResult>
}
