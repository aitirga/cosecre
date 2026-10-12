/**
 * The Esfer@ dashboard: one read of a budget and the centre's treasury, already
 * shaped for the screen. Fixed read capabilities only — no URLs, credentials,
 * scripts or write payloads cross this bridge.
 */
import type { SferaRequestTrace } from './contract'

export type SferaBudgetKind = 'G' | 'M' | string

export interface SferaDashboardBudget {
  id: number
  year: number
  kind: SferaBudgetKind
  /** «General», «Menjador», or esfer@'s own code when it is another kind. */
  kindLabel: string
  state: string
  stateLabel: string
  approvedAt: string | null
  changedAt: string | null
  /** Romanent carried over from the previous year. */
  remnant: number
}

/** A budget line as esfer@'s «Estat d'execució del pressupost» reports it. */
export interface SferaLine {
  code: string
  name: string
  kind: 'I' | 'D'
  /** Codi finalista: the earmarked fund, empty for ordinary money. */
  fund: string
  /** Code of the parent line, for a subpartida. */
  parent: string | null
  budgeted: number
  /** Ingressos reconeguts / despeses imputades. */
  imputed: number
  committed: number
  /** Saldo de la partida: budgeted − imputed. Negative is over-executed. */
  available: number
}

export interface SferaAccount {
  code: string
  name: string
  kind: 'bank' | 'cash'
  balance: number
  active: boolean
  main: boolean
  /** Last four digits of a bank account, or the cash box's responsible person. */
  detail: string | null
}

export interface SferaMonth { month: string; collected: number; paid: number }
export interface SferaBalancePoint { date: string; balance: number }

export interface SferaMovement {
  date: string
  type: string
  typeLabel: string
  description: string
  account: string
  amount: number
}

export interface SferaInvoiceRow {
  id: number
  code: string
  date: string | null
  supplier: string
  number: string
  description: string
  total: number
  paid: number
  pending: number
  /** F factura, AB abonament. */
  type: string
  cancelled: boolean
}

export interface SferaIncomeRow {
  id: number
  code: string
  date: string | null
  contributor: string
  description: string
  total: number
  collected: number
  pending: number
  /** I ingrés, DI devolució d'ingrés. */
  type: string
  cancelled: boolean
}

export interface SferaDashboard {
  centre: { code: string; name: string }
  budgets: SferaDashboardBudget[]
  budget: SferaDashboardBudget
  execution: {
    income: { budgeted: number; imputed: number; available: number }
    expense: { budgeted: number; imputed: number; available: number }
    collections: { total: number; year: number; previous: number }
    payments: { total: number; year: number; previous: number }
    /** Income budgeted − expense budgeted; esfer@ wants it at zero. */
    balance: number
  }
  lines: SferaLine[]
  treasury: {
    accounts: SferaAccount[]
    total: number
    /** Daily treasury balance through the latest year with movements. */
    series: SferaBalancePoint[]
    seriesYear: number | null
  }
  /** Money in and out of banks and cash boxes for this budget, transfers between them left out. */
  months: SferaMonth[]
  movements: SferaMovement[]
  invoices: SferaInvoiceRow[]
  incomes: SferaIncomeRow[]
  eInvoicesPending: number
  requests: SferaRequestTrace[]
  durationMs: number
  completedAt: string
}

export interface SferaCentreOption { code: string; name: string }

export type SferaDashboardResult =
  | { ok: true; data: SferaDashboard }
  | { ok: false; error: string; /** Present when Esfer@ is waiting for a centre to be chosen. */ centres?: SferaCentreOption[] }

export interface SferaDashboardBridge {
  load(input: { budgetId?: number }): Promise<SferaDashboardResult>
  /** Chooses a centre in Esfer@'s own «Escolliu el centre» dialog. */
  selectCentre(code: string): Promise<SferaDashboardResult>
}
