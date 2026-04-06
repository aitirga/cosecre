import type {
  AuthTokens,
  InvoiceRecord,
  InvoiceUpdate,
  JobRead,
  RefreshResult,
  UploadResponse,
  User,
  WorkspaceSettings,
} from './types'

const API_BASE = import.meta.env.VITE_API_BASE_URL ?? '/api'
const ACCESS_KEY = 'cosecre.accessToken'
const REFRESH_KEY = 'cosecre.refreshToken'

export class ApiError extends Error {
  status: number

  constructor(status: number, message: string) {
    super(message)
    this.status = status
  }
}

let accessToken = localStorage.getItem(ACCESS_KEY)
let refreshToken = localStorage.getItem(REFRESH_KEY)

function persistTokens(tokens: AuthTokens) {
  accessToken = tokens.access_token
  refreshToken = tokens.refresh_token
  localStorage.setItem(ACCESS_KEY, tokens.access_token)
  localStorage.setItem(REFRESH_KEY, tokens.refresh_token)
}

export function clearTokens() {
  accessToken = null
  refreshToken = null
  localStorage.removeItem(ACCESS_KEY)
  localStorage.removeItem(REFRESH_KEY)
}

async function parseResponse<T>(response: Response): Promise<T> {
  const text = await response.text()
  const data = text ? JSON.parse(text) : null

  if (!response.ok) {
    const detail = data?.detail ?? data?.message ?? response.statusText
    throw new ApiError(response.status, detail)
  }

  return data as T
}

async function refreshSession(): Promise<boolean> {
  if (!refreshToken) {
    return false
  }

  const response = await fetch(`${API_BASE}/auth/refresh`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ refresh_token: refreshToken }),
  })

  if (!response.ok) {
    clearTokens()
    return false
  }

  const tokens = await parseResponse<AuthTokens>(response)
  persistTokens(tokens)
  return true
}

async function request<T>(path: string, init: RequestInit = {}, retry = true): Promise<T> {
  const headers = new Headers(init.headers ?? {})
  const isFormData = init.body instanceof FormData

  if (!isFormData && !headers.has('Content-Type')) {
    headers.set('Content-Type', 'application/json')
  }

  if (accessToken) {
    headers.set('Authorization', `Bearer ${accessToken}`)
  }

  const response = await fetch(`${API_BASE}${path}`, { ...init, headers })

  if (
    response.status === 401 &&
    retry &&
    refreshToken &&
    !['/auth/refresh', '/auth/login', '/auth/register'].includes(path)
  ) {
    const refreshed = await refreshSession()
    if (refreshed) {
      return request<T>(path, init, false)
    }
  }

  return parseResponse<T>(response)
}

export const api = {
  async register(payload: { email: string; password: string }) {
    const tokens = await request<AuthTokens>('/auth/register', {
      method: 'POST',
      body: JSON.stringify(payload),
    })
    persistTokens(tokens)
    return tokens
  },
  async login(payload: { email: string; password: string }) {
    const tokens = await request<AuthTokens>('/auth/login', {
      method: 'POST',
      body: JSON.stringify(payload),
    })
    persistTokens(tokens)
    return tokens
  },
  me() {
    return request<User>('/auth/me')
  },
  async refreshIfNeeded() {
    if (!accessToken && refreshToken) {
      await refreshSession()
    }
  },
  hasStoredSession() {
    return Boolean(accessToken || refreshToken)
  },
  getInvoices() {
    return request<InvoiceRecord[]>('/invoices')
  },
  getInvoice(internalDocNumber: string) {
    return request<InvoiceRecord>(`/invoices/${internalDocNumber}`)
  },
  getJob(jobId: string) {
    return request<JobRead>(`/invoices/jobs/${jobId}`)
  },
  refreshInvoices() {
    return request<RefreshResult>('/invoices/refresh')
  },
  uploadInvoice(file: File) {
    const formData = new FormData()
    formData.append('file', file)
    return request<UploadResponse>('/invoices/upload', {
      method: 'POST',
      body: formData,
    })
  },
  updateInvoice(internalDocNumber: string, payload: InvoiceUpdate) {
    return request<InvoiceRecord>(`/invoices/${internalDocNumber}`, {
      method: 'PATCH',
      body: JSON.stringify(payload),
    })
  },
  validateInvoice(internalDocNumber: string) {
    return request<InvoiceRecord>(`/invoices/${internalDocNumber}/validate`, {
      method: 'POST',
    })
  },
  deleteInvoice(internalDocNumber: string) {
    return request<void>(`/invoices/${internalDocNumber}`, { method: 'DELETE' })
  },
  async getInvoiceFileBlob(internalDocNumber: string): Promise<string> {
    const headers = new Headers()
    if (accessToken) headers.set('Authorization', `Bearer ${accessToken}`)
    const response = await fetch(`${API_BASE}/invoices/${internalDocNumber}/file`, { headers })
    if (!response.ok) throw new ApiError(response.status, 'File not found')
    const blob = await response.blob()
    return URL.createObjectURL(blob)
  },
  getSettings() {
    return request<WorkspaceSettings>('/settings')
  },
  updateSettings(payload: WorkspaceSettings) {
    return request<WorkspaceSettings>('/settings', {
      method: 'PUT',
      body: JSON.stringify(payload),
    })
  },
}
