import { request } from '../../api/client'
import type { Capability, ExportContext, ExportInvoice, ExportPlan, ExportPlanSummary, PreflightResult } from '../../sfera/export-contract'

/** Hub calls for export plans; the contract itself lives in ``sfera/export-contract.ts``. */
const BASE = '/sfera'
const json = (body: unknown): RequestInit => ({ method: 'POST', body: JSON.stringify(body) })

export const exportApi = {
  capabilities: () => request<Capability[]>(`${BASE}/capabilities`),
  preflight: (context: ExportContext, invoices: ExportInvoice[]) => request<PreflightResult[]>(`${BASE}/preflight`, json({ context, invoices })),
  list: () => request<ExportPlanSummary[]>(`${BASE}/export-plans`),
  get: (id: string) => request<ExportPlan>(`${BASE}/export-plans/${id}`),
  create: (context: ExportContext, invoices: ExportInvoice[]) => request<ExportPlan>(`${BASE}/export-plans`, json({ context, invoices })),
  approve: (plan: ExportPlan) => request<ExportPlan>(`${BASE}/export-plans/${plan.id}/approve`, json({ plan_hash: plan.plan_hash })),
  cancel: (id: string) => request<ExportPlan>(`${BASE}/export-plans/${id}/cancel`, { method: 'POST' }),
  remove: (id: string) => request<void>(`${BASE}/export-plans/${id}`, { method: 'DELETE' }),
  removeItem: (id: string, itemId: number) => request<ExportPlan>(`${BASE}/export-plans/${id}/items/${itemId}`, { method: 'DELETE' }),
  recover: (id: string, itemId: number) => request<ExportPlan>(`${BASE}/export-plans/${id}/items/${itemId}/recover`, { method: 'POST' }),
}
