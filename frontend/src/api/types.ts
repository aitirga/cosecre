export type ExtractionStatus =
  | 'pending'
  | 'processing'
  | 'written_to_sheet'
  | 'needs_validation'
  | 'validated'
  | 'error'

// ── Hub discovery ───────────────────────────────────────────────────────────

export interface HubCapabilities {
  auth: boolean
  app_settings: boolean
  llm: boolean
  documents: boolean
  google_sheets: boolean
  classifier?: boolean
}

/** The shape of `GET /meta` — the one hub endpoint that answers without a token. */
export interface HubMeta {
  name: string
  product: string
  version: string
  api_version: string
  api_prefix: string
  capabilities: HubCapabilities
  apps: string[]
  accepts_registration: boolean
  has_users: boolean
}

// ── Identity ────────────────────────────────────────────────────────────────

export interface User {
  id: number
  email: string
  display_name: string | null
  is_admin: boolean
  is_active: boolean
  created_at: string
  last_login_at: string | null
}

export interface AuthTokens {
  access_token: string
  refresh_token: string
  token_type: string
  expires_in: number
  user: User
}

export interface SessionInfo {
  id: number
  client: string | null
  client_label: string | null
  created_at: string
  expires_at: string
}

export interface UserCreate {
  email: string
  password: string
  display_name?: string | null
  is_admin?: boolean
}

export interface UserUpdate {
  display_name?: string | null
  is_admin?: boolean
  is_active?: boolean
  password?: string
}

// ── Model gateway ───────────────────────────────────────────────────────────

export interface LlmProvider {
  id: string
  label: string
  configured: boolean
  default_model: string
  models: string[]
}

// ── Documents ───────────────────────────────────────────────────────────────

export type SheetState = 'synced' | 'pending' | 'removed'
export type CaptureSource = 'camera' | 'file'

/** Why a field holds the value it does, when a model chose it. */
export interface AiHint {
  source: 'jev' | 'openai' | 'jev+openai' | 'migracio'
  confidence?: number | null
  alternative?: string | null
  review: boolean
}

/** Every register column a person can change. Dates are ISO (`yyyy-mm-dd`). */
export interface DocumentFields {
  tipus_document: string
  origen: string
  num_factura: string
  data_factura: string | null
  proveidor: string
  cif_proveidor: string
  carrer: string
  codi_postal: string
  ciutat: string
  compte_corrent: string
  cif_proveit: string
  import: number | null
  descripcio: string
  descripcio_compra: string
  pagament: string
  pagament_observacions: string
  metode_pagament: string
  data_pagament: string | null
  subministrat: string
  pressupost_afectat: string
  responsable_nom: string
  responsable_email: string
  validat: boolean
}

/** One model run, step by step: what the vision model proposed, what Jev scored, what was kept. */
export interface AiTrace {
  at?: string
  vision?: { model: string | null; proposal: Record<string, unknown> }
  jev?: {
    model: string | null
    status: 'ok' | 'off' | 'error' | 'skipped'
    error?: string
    answers: Record<string, { label: string; confidence: number; probabilities: Record<string, number> }>
  }
  final?: Record<string, { value: unknown; hint: AiHint | null }>
  only_empty?: boolean
  filled?: string[]
}

export interface DocumentRecord extends DocumentFields {
  num_doc_intern: string
  file_link: string
  file_url: string | null
  /** The name the original is downloaded under — the same as on Drive. */
  file_name: string | null
  file_size: number | null
  drive_url: string | null
  source_file_name: string | null
  source_file_type: string | null
  transcripcio: string
  extraction_status: ExtractionStatus
  sheet_state: SheetState
  sheet_row_ref: number | null
  legacy_type: 'invoice' | 'ticket' | null
  ai_hints: Record<string, AiHint>
  ai_trace: AiTrace | null
  iban_valid: boolean | null
  created_at: string | null
  updated_at: string | null
  error_message: string | null
}

/** Someone already named as an entry's responsible person. */
export interface Responsable {
  nom: string
  email: string
}

export interface ResponsableSearch {
  matches: Responsable[]
  /** Set when what was typed looks like a slip of a known person ("Susna"). */
  suggestion: Responsable | null
}

export type DocumentUpdate = Partial<Omit<DocumentFields, 'origen'>>

export interface UploadResponse {
  job_id: string
  internal_doc_number: string
  status: ExtractionStatus
}

export interface JobRead {
  id: string
  internal_doc_number: string
  status: ExtractionStatus
  error_message: string | null
  sheet_row_ref: number | null
  created_at: string
  updated_at: string
}

export interface SyncResult {
  sheet_configured: boolean
  refreshed: number
  imported: number
  updated: number
  pushed: number
  removed: number
  waiting: number
  conflicts: number
  error: string | null
}

export type DiffStatus =
  | 'db_changed'
  | 'not_in_sheet'
  | 'sheet_changed'
  | 'new_in_sheet'
  | 'missing'
  | 'conflict'

export interface DiffEntry {
  reference: string
  status: DiffStatus
  row: number | null
  num_factura: string
  proveidor: string
  changes: { field: string; label: string; db: unknown; sheet: unknown }[]
}

export interface SyncDiff {
  sheet_configured: boolean
  entries: DiffEntry[]
  counts: Partial<Record<DiffStatus, number>>
}

export interface SyncApplied {
  applied: number
  backup: string | null
}

export interface WorkspaceSettings {
  spreadsheet_url: string | null
  registry_sheet_name: string
  sheet_name: string
  ticket_sheet_name: string
  openai_model: string
  extraction_prompt: string
  polling_interval_seconds: number
  classifier_configured?: boolean
  drive_folder_configured?: boolean
}

export interface MigrationIssue {
  tab: string
  row: number | null
  reference: string | null
  message: string
}

export interface MigrationReport {
  dry_run: boolean
  tabs: Record<string, number>
  already_migrated: number
  to_create: number
  created: number
  references_generated: number
  from_database: number
  with_file: number
  issues: MigrationIssue[]
  enrichment_pending: number
  enrichment_done: number
  enrichment_running: boolean
  drive_missing: number
  drive_running: boolean
  drive_configured: boolean
  completed_at: string | null
}

// ── Backups ─────────────────────────────────────────────────────────────────

export interface BackupItem {
  name: string
  size: number
  created_at: string
  kind: string
  kind_label: string
  reason: string
  author: string | null
  documents: number | null
  added: number | null
  removed: number | null
  changed: number | null
  has_sheet: boolean
}

export interface BackupComparison {
  name: string
  entries: {
    reference: string
    status: 'only_in_backup' | 'only_now' | 'changed'
    num_factura: string
    proveidor: string
    changes: { field: string; label: string; backup: unknown; now: unknown }[]
  }[]
  counts: Record<string, number>
}

export interface BackupOverview {
  backups: BackupItem[]
  directory: string
  keep: number
  interval_hours: number
  offsite_configured: boolean
  last_offsite_at: string | null
  last_error: string | null
}
