export type DocumentType = 'invoice' | 'ticket'

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
  aim: boolean
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

export interface InvoiceRecord {
  document_type: DocumentType
  num_factura: string
  data_factura: string
  proveidor: string
  cif_proveidor: string
  adreca_proveidor: string
  import: number | null
  cif_proveit: string
  descripcio: string
  pressupost_afectat: string
  num_doc_intern: string
  file_link: string
  file_url: string | null
  validat: boolean
  source_file_name: string | null
  source_file_type: string | null
  extraction_status: ExtractionStatus
  sheet_row_ref: number | null
  created_at: string | null
  updated_at: string | null
  error_message: string | null
}

export interface InvoiceUpdate {
  num_factura?: string
  data_factura?: string
  proveidor?: string
  cif_proveidor?: string
  adreca_proveidor?: string
  import?: string | number | null
  cif_proveit?: string
  descripcio?: string
  pressupost_afectat?: string
  validat?: boolean
}

export interface UploadResponse {
  job_id: string
  document_type: DocumentType
  internal_doc_number: string
  status: ExtractionStatus
}

export interface JobRead {
  id: string
  document_type: DocumentType
  internal_doc_number: string
  status: ExtractionStatus
  error_message: string | null
  sheet_row_ref: number | null
  created_at: string
  updated_at: string
}

export interface WorkspaceSettings {
  spreadsheet_url: string | null
  sheet_name: string
  ticket_sheet_name: string
  openai_model: string
  extraction_prompt: string
  polling_interval_seconds: number
}

export interface RefreshResult {
  refreshed: number
}
