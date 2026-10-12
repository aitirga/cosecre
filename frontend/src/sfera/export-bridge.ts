import type { InvoiceWriteTrace } from './invoice-bridge'

/** The desktop runner for Hub export plans (``/api/v1/sfera/export-plans``). */
export interface ExportRunResult {
  planId: string
  itemId: number
  outcome: 'succeeded' | 'uncertain' | 'failed'
  remoteCode: string | null
  error: string | null
  requests: InvoiceWriteTrace[]
}
export interface DiagnosticCheck { id: string; label: string; status: 'ok' | 'warn' | 'fail'; detail: string }
export interface DiagnosticReport {
  centre: string
  checkedAt: string
  ready: boolean
  checks: DiagnosticCheck[]
  /** A synthetic invoice from the live catalog through the Hub preflight (nothing kept). */
  preflight: { state: string; problems: string[] } | null
  requests: InvoiceWriteTrace[]
}
export interface SferaExportBridge {
  /** Claims the approved item in the Hub, writes it with the portal session and reports back.
   *  Only IDs cross the bridge: the payload comes from the Hub, never from the page. */
  run(planId: string, itemId: number): Promise<ExportRunResult>
  /** Reads the portal to settle an uncertain or conflicting item in the Hub. */
  reconcile(planId: string, itemId: number): Promise<ExportRunResult>
  /** Read-only readiness check of the open session. */
  diagnose(): Promise<DiagnosticReport>
}
