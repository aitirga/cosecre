export type ExtractionStatus =
  | 'pending'
  | 'processing'
  | 'written_to_sheet'
  | 'needs_validation'
  | 'validated'
  | 'error'

export interface User {
  id: number
  email: string
  is_admin: boolean
  created_at: string
}

export interface AuthTokens {
  access_token: string
  refresh_token: string
  token_type: string
  user: User
}

export interface InvoiceRecord {
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

export interface WorkspaceSettings {
  spreadsheet_url: string | null
  sheet_name: string
  openai_model: string
  extraction_prompt: string
  polling_interval_seconds: number
}

export interface RefreshResult {
  refreshed: number
}
