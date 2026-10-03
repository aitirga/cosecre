import { trackedFetch } from './loading'
/**
 * The Cosecre Hub client.
 *
 * Shared verbatim by the web app and the desktop app, which is why nothing in
 * here assumes a browser origin or `localStorage`: both the base URL and the
 * token store are injected through `configureApi`. In the browser the defaults
 * are right and nobody calls it; in Electron the main process supplies both.
 */
import type {
  AuthTokens,
  CaixetaStatus,
  DocumentBrief,
  DocumentPayment,
  MatchRun,
  Movement,
  MovementDetail,
  ReconcileStatement,
  Statement,
  BackupComparison,
  BackupOverview,
  CaptureSource,
  DocumentRecord,
  DocumentUpdate,
  HubMeta,
  JobRead,
  LlmProvider,
  MigrationReport,
  ResponsableSearch,
  SessionInfo,
  SyncApplied,
  SyncDiff,
  SyncResult,
  UploadResponse,
  User,
  UserCreate,
  UserUpdate,
  WorkspaceSettings,
} from './types'

const ACCESS_KEY = 'cosecre.accessToken'
const REFRESH_KEY = 'cosecre.refreshToken'

/** Endpoints that must never trigger a refresh-and-retry of their own. */
const NO_RETRY_PATHS = ['/auth/refresh', '/auth/login', '/auth/register', '/auth/logout']

export class ApiError extends Error {
  status: number
  /** The parsed error body, for callers that act on more than the message. */
  data: unknown

  constructor(status: number, message: string, data: unknown = null) {
    super(message)
    this.status = status
    this.data = data
  }
}

/**
 * Somewhere to keep tokens across restarts.
 *
 * Synchronous on purpose: the very first request has to be able to attach a
 * token without awaiting anything.
 */
export interface TokenStorage {
  get(key: string): string | null
  set(key: string, value: string): void
  remove(key: string): void
}

/** `localStorage` is unavailable on some origins (notably `file://`), and
 *  throwing there would take the whole app down, so every call is guarded. */
const browserStorage: TokenStorage = {
  get(key) {
    try {
      return globalThis.localStorage?.getItem(key) ?? null
    } catch {
      return null
    }
  },
  set(key, value) {
    try {
      globalThis.localStorage?.setItem(key, value)
    } catch {
      /* a session that cannot be persisted still works until reload */
    }
  },
  remove(key) {
    try {
      globalThis.localStorage?.removeItem(key)
    } catch {
      /* nothing to do */
    }
  },
}

export interface ApiConfig {
  /** Hub API root, e.g. `https://hub.example.com/api/v1`. No trailing slash. */
  baseUrl?: string
  storage?: TokenStorage
  /** Recorded on the session so a user can tell their devices apart. */
  client?: string
  clientLabel?: string
  /** Called when a session is gone for good, so the UI can return to sign-in. */
  onUnauthorized?: () => void
}

let baseUrl = normalizeBaseUrl(import.meta.env.VITE_API_BASE_URL ?? '/api/v1')
let storage: TokenStorage = browserStorage
let clientName = 'web'
let clientLabel: string | undefined
let onUnauthorized: (() => void) | undefined

let accessToken: string | null = null
let refreshToken: string | null = null
let tokensLoaded = false

function normalizeBaseUrl(value: string): string {
  return value.replace(/\/+$/, '')
}

function loadTokens() {
  if (tokensLoaded) return
  accessToken = storage.get(ACCESS_KEY)
  refreshToken = storage.get(REFRESH_KEY)
  tokensLoaded = true
}

export function configureApi(config: ApiConfig) {
  if (config.baseUrl !== undefined) baseUrl = normalizeBaseUrl(config.baseUrl)
  if (config.storage) {
    storage = config.storage
    // A new store means the cached pair belongs to the old one.
    tokensLoaded = false
    accessToken = null
    refreshToken = null
  }
  if (config.client) clientName = config.client
  if (config.clientLabel !== undefined) clientLabel = config.clientLabel
  if (config.onUnauthorized) onUnauthorized = config.onUnauthorized
}

export function getApiBaseUrl() {
  return baseUrl
}

function persistTokens(tokens: AuthTokens) {
  accessToken = tokens.access_token
  refreshToken = tokens.refresh_token
  tokensLoaded = true
  storage.set(ACCESS_KEY, tokens.access_token)
  storage.set(REFRESH_KEY, tokens.refresh_token)
}

export function clearTokens() {
  accessToken = null
  refreshToken = null
  tokensLoaded = true
  storage.remove(ACCESS_KEY)
  storage.remove(REFRESH_KEY)
}

async function parseResponse<T>(response: Response): Promise<T> {
  const text = await response.text()
  let data: unknown = null

  if (text) {
    try {
      data = JSON.parse(text)
    } catch {
      if (!response.ok) {
        throw new ApiError(response.status, text)
      }
      throw new ApiError(response.status, 'El servidor ha retornat una resposta no vàlida.')
    }
  }

  if (!response.ok) {
    throw new ApiError(response.status, describeError(data, response.statusText), data)
  }

  return data as T
}

/** FastAPI reports validation failures as a list of objects, not a string. */
function describeError(data: unknown, fallback: string): string {
  const payload = data as { detail?: unknown; message?: string } | null
  const detail = payload?.detail
  if (typeof detail === 'string') return detail
  if (Array.isArray(detail)) {
    const messages = detail
      .map((item) => (item as { msg?: string })?.msg?.replace(/^Value error, /, ''))
      .filter((msg): msg is string => Boolean(msg))
    if (messages.length) return messages.join('. ')
  }
  return payload?.message ?? fallback
}

/**
 * A single in-flight refresh, shared by every caller.
 *
 * The hub rotates refresh tokens and revokes the one it was given, so two
 * concurrent refreshes would race: the second would present a spent token and
 * lose the session. Coalescing them is not an optimisation, it is required.
 */
let refreshInFlight: Promise<boolean> | null = null

function refreshSession(): Promise<boolean> {
  loadTokens()
  if (!refreshToken) return Promise.resolve(false)
  if (refreshInFlight) return refreshInFlight

  const attempted = refreshToken
  refreshInFlight = (async () => {
    try {
      const response = await trackedFetch(`${baseUrl}/auth/refresh`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ refresh_token: attempted }),
      })
      if (!response.ok) {
        clearTokens()
        onUnauthorized?.()
        return false
      }
      persistTokens((await response.json()) as AuthTokens)
      return true
    } catch {
      // A network failure is not proof the session is dead — keep the tokens so
      // the next attempt can succeed once the hub is reachable again.
      return false
    } finally {
      refreshInFlight = null
    }
  })()

  return refreshInFlight
}

/**
 * A bearer-authenticated `fetch`, with one refresh-and-retry, returning the raw
 * `Response`.
 *
 * `request` cannot serve every caller: it reads the whole body as JSON, which is
 * wrong for a file download and impossible for a stream. Retrying is safe here
 * only because both of those are GETs — the retry replays the request, so this
 * must never carry a body that writes.
 */
export async function authorizedFetch(path: string, init: RequestInit = {}): Promise<Response> {
  loadTokens()

  const send = () => {
    const headers = new Headers(init.headers ?? {})
    if (accessToken) headers.set('Authorization', `Bearer ${accessToken}`)
    return trackedFetch(`${baseUrl}${path}`, { ...init, headers })
  }

  let response: Response
  try {
    response = await send()
  } catch (error) {
    throw new ApiError(0, unreachableMessage(error))
  }

  if (response.status === 401 && (await refreshSession())) {
    try {
      response = await send()
    } catch (error) {
      throw new ApiError(0, unreachableMessage(error))
    }
  }

  return response
}

/** Fetch a protected file as an object URL. Callers own it and must revoke it. */
export async function fetchBlobUrl(path: string): Promise<string> {
  const response = await authorizedFetch(path)
  if (!response.ok) {
    throw new ApiError(response.status, response.statusText || "No s'ha pogut obtenir el fitxer.")
  }
  return URL.createObjectURL(await response.blob())
}

/** The file name a `Content-Disposition` header carries, RFC 5987 form first. */
function dispositionName(header: string | null): string | null {
  if (!header) return null
  const encoded = /filename\*=(?:UTF-8|utf-8)''([^;]+)/.exec(header)
  if (encoded) return decodeURIComponent(encoded[1].trim())
  const plain = /filename="?([^";]+)"?/.exec(header)
  return plain ? plain[1].trim() : null
}

/**
 * Download a protected file to the person's disk, under the name the hub gives
 * it. A plain link cannot do it: it would not carry the bearer token.
 */
export async function saveFile(path: string, fallbackName: string): Promise<void> {
  const response = await authorizedFetch(path)
  if (!response.ok) {
    let detail = response.statusText || "No s'ha pogut descarregar el fitxer."
    try {
      const body = await response.json()
      if (typeof body?.detail === 'string') detail = body.detail
    } catch {
      // Not JSON; the status text will do.
    }
    throw new ApiError(response.status, detail)
  }
  const url = URL.createObjectURL(await response.blob())
  const link = document.createElement('a')
  link.href = url
  link.download = dispositionName(response.headers.get('Content-Disposition')) ?? fallbackName
  document.body.appendChild(link)
  link.click()
  link.remove()
  window.setTimeout(() => URL.revokeObjectURL(url), 1000)
}

export async function request<T>(path: string, init: RequestInit = {}, retry = true): Promise<T> {
  loadTokens()
  const headers = new Headers(init.headers ?? {})
  const isFormData = init.body instanceof FormData

  // Setting Content-Type on a FormData body would clobber the multipart
  // boundary the browser generates.
  if (!isFormData && init.body !== undefined && !headers.has('Content-Type')) {
    headers.set('Content-Type', 'application/json')
  }
  if (accessToken) {
    headers.set('Authorization', `Bearer ${accessToken}`)
  }

  let response: Response
  try {
    response = await trackedFetch(`${baseUrl}${path}`, { ...init, headers })
  } catch (error) {
    throw new ApiError(0, unreachableMessage(error))
  }

  if (response.status === 401 && retry && refreshToken && !NO_RETRY_PATHS.includes(path)) {
    if (await refreshSession()) {
      return request<T>(path, init, false)
    }
  }

  return parseResponse<T>(response)
}

function unreachableMessage(error: unknown): string {
  const detail = error instanceof Error ? error.message : String(error)
  return `No s'ha pogut connectar amb el hub de Cosecre a ${baseUrl}. ${detail}`
}

const RECORDS = '/documents/records'

/**
 * Ask a hub to describe itself. Used to validate a URL before signing in, so it
 * takes its own base URL and never sends credentials.
 */
export async function fetchHubMeta(url: string = baseUrl): Promise<HubMeta> {
  const root = normalizeBaseUrl(url)
  let response: Response
  try {
    response = await trackedFetch(`${root}/meta`, { headers: { Accept: 'application/json' } })
  } catch (error) {
    throw new ApiError(0, `Could not reach a Cosecre Hub at ${root}. ${describeCause(error)}`)
  }
  const meta = await parseResponse<HubMeta>(response)
  if (meta.product !== 'cosecre-hub') {
    throw new ApiError(response.status, `${root} answered, but it is not a Cosecre Hub.`)
  }
  return meta
}

function describeCause(error: unknown): string {
  return error instanceof Error ? error.message : String(error)
}

export const api = {
  // ── Discovery ───────────────────────────────────────────────────────────
  meta() {
    return request<HubMeta>('/meta')
  },

  // ── Auth ────────────────────────────────────────────────────────────────
  async register(payload: { email: string; password: string; display_name?: string }) {
    const tokens = await request<AuthTokens>('/auth/register', {
      method: 'POST',
      body: JSON.stringify({ ...payload, client: clientName, client_label: clientLabel }),
    })
    persistTokens(tokens)
    return tokens
  },
  async login(payload: { email: string; password: string }) {
    const tokens = await request<AuthTokens>('/auth/login', {
      method: 'POST',
      body: JSON.stringify({ ...payload, client: clientName, client_label: clientLabel }),
    })
    persistTokens(tokens)
    return tokens
  },
  /** Revoke this session on the hub, then forget it locally either way. */
  async logout() {
    loadTokens()
    const token = refreshToken
    clearTokens()
    if (!token) return
    try {
      await request('/auth/logout', { method: 'POST', body: JSON.stringify({ refresh_token: token }) })
    } catch {
      // Signing out must never fail visibly: the tokens are already gone here.
    }
  },
  me() {
    return request<User>('/auth/me')
  },
  sessions() {
    return request<SessionInfo[]>('/auth/sessions')
  },
  changePassword(payload: { current_password: string; new_password: string }) {
    return request<{ message: string }>('/auth/password', {
      method: 'POST',
      body: JSON.stringify(payload),
    })
  },
  async refreshIfNeeded() {
    loadTokens()
    if (!accessToken && refreshToken) {
      await refreshSession()
    }
  },
  hasStoredSession() {
    loadTokens()
    return Boolean(accessToken || refreshToken)
  },

  // ── Users (admin) ───────────────────────────────────────────────────────
  listUsers() {
    return request<User[]>('/users')
  },
  createUser(payload: UserCreate) {
    return request<User>('/users', { method: 'POST', body: JSON.stringify(payload) })
  },
  updateUser(userId: number, payload: UserUpdate) {
    return request<User>(`/users/${userId}`, { method: 'PATCH', body: JSON.stringify(payload) })
  },
  disableUser(userId: number) {
    return request<{ message: string }>(`/users/${userId}`, { method: 'DELETE' })
  },

  // ── Model gateway ───────────────────────────────────────────────────────
  llmProviders() {
    return request<LlmProvider[]>('/llm/providers')
  },

  // ── Documents ───────────────────────────────────────────────────────────
  getDocuments() {
    return request<DocumentRecord[]>(RECORDS)
  },
  getDocument(reference: string) {
    return request<DocumentRecord>(`${RECORDS}/${reference}`)
  },
  searchResponsables(field: 'nom' | 'email', q: string) {
    const params = new URLSearchParams({ field, q })
    return request<ResponsableSearch>(`/documents/responsables?${params}`)
  },
  getJob(jobId: string) {
    return request<JobRead>(`${RECORDS}/jobs/${jobId}`)
  },
  syncDocuments() {
    return request<SyncResult>(`${RECORDS}/sync`, { method: 'POST' })
  },
  syncDiff() {
    return request<SyncDiff>(`${RECORDS}/sync/diff`)
  },
  /** Sheet → database. `references` limits it; `row:<n>` picks a typed row. */
  syncPull(references?: string[]) {
    return request<SyncApplied>(`${RECORDS}/sync/pull`, {
      method: 'POST',
      body: JSON.stringify({ references: references ?? null }),
    })
  },
  /** Database → sheet. */
  syncPush(references?: string[]) {
    return request<SyncApplied>(`${RECORDS}/sync/push`, {
      method: 'POST',
      body: JSON.stringify({ references: references ?? null }),
    })
  },
  /** `camera` marks the entry as a photo; anything picked from disk is an original. */
  uploadDocument(file: File, source: CaptureSource) {
    const formData = new FormData()
    formData.append('file', file)
    formData.append('source', source)
    return request<UploadResponse>(`${RECORDS}/upload`, { method: 'POST', body: formData })
  },
  updateDocument(reference: string, payload: DocumentUpdate) {
    return request<DocumentRecord>(`${RECORDS}/${reference}`, {
      method: 'PATCH',
      body: JSON.stringify(payload),
    })
  },
  validateDocument(reference: string) {
    return request<DocumentRecord>(`${RECORDS}/${reference}/validate`, { method: 'POST' })
  },
  deleteDocument(reference: string) {
    return request<void>(`${RECORDS}/${reference}`, { method: 'DELETE' })
  },
  /**
   * Fetch the stored original as an object URL.
   *
   * It goes through `fetch` rather than an `<img src>` because the endpoint
   * needs a bearer token. Callers own the URL and must revoke it.
   */
  getDocumentFileBlob(reference: string): Promise<string> {
    return fetchBlobUrl(`${RECORDS}/${reference}/file`)
  },
  /** Like `getDocumentFileBlob`, keeping the MIME type: a photo and a PDF are shown differently. */
  async getDocumentFile(reference: string): Promise<{ url: string; type: string }> {
    const response = await authorizedFetch(`${RECORDS}/${reference}/file`)
    if (!response.ok) {
      throw new ApiError(response.status, response.statusText || "No s'ha pogut obtenir el fitxer.")
    }
    const blob = await response.blob()
    return { url: URL.createObjectURL(blob), type: blob.type }
  },
  downloadDocumentFile(reference: string, fallbackName: string): Promise<void> {
    return saveFile(`${RECORDS}/${reference}/file`, fallbackName)
  },
  downloadAllFiles(): Promise<void> {
    return saveFile(`${RECORDS}/files.zip`, 'cosecre-originals.zip')
  },

  // ── Migration from the two old tabs ─────────────────────────────────────
  previewMigration() {
    return request<MigrationReport>('/documents/migration')
  },
  migrationStatus() {
    return request<MigrationReport>('/documents/migration/status')
  },
  runMigration() {
    return request<MigrationReport>('/documents/migration', { method: 'POST' })
  },
  resumeEnrichment() {
    return request<MigrationReport>('/documents/migration/enrich', { method: 'POST' })
  },
  uploadOriginalsToDrive() {
    return request<MigrationReport>('/documents/migration/drive', { method: 'POST' })
  },

  // ── Backups ─────────────────────────────────────────────────────────────
  listBackups() {
    return request<BackupOverview>('/backups')
  },
  createBackup() {
    return request<BackupOverview>('/backups', { method: 'POST' })
  },
  downloadBackup(name: string): Promise<string> {
    return fetchBlobUrl(`/backups/${encodeURIComponent(name)}`)
  },
  compareBackup(name: string) {
    return request<BackupComparison>(`/backups/${encodeURIComponent(name)}/compare`)
  },
  restoreBackup(name: string) {
    return request<{ restored: number; safety_backup: string; overview: BackupOverview }>(
      `/backups/${encodeURIComponent(name)}/restore`,
      { method: 'POST' },
    )
  },
  uploadBackup(file: File) {
    const formData = new FormData()
    formData.append('file', file)
    return request<BackupOverview>('/backups/upload', { method: 'POST', body: formData })
  },

  // ── Bank statements (ingestion) ─────────────────────────────────────────
  /** Excel or prepaid PDF. A 409 with `code: 'needs_account'` asks for `compte`. */
  uploadStatement(file: File, compte?: string) {
    const formData = new FormData()
    formData.append('file', file)
    if (compte) formData.append('compte', compte)
    return request<Statement>('/statements/upload', { method: 'POST', body: formData })
  },
  listStatements() {
    return request<Statement[]>('/statements/imports')
  },
  statementMovements(statementId: number) {
    return request<Movement[]>(`/statements/imports/${statementId}/movements`)
  },
  deleteStatement(statementId: number) {
    return request<void>(`/statements/imports/${statementId}`, { method: 'DELETE' })
  },
  downloadStatement(statement: Statement): Promise<void> {
    return saveFile(`/statements/imports/${statement.id}/file`, statement.file_name || 'extracte')
  },
  updateMovement(movementId: number, payload: { tipus?: string; categoria?: string }) {
    return request<Movement>(`/statements/movements/${movementId}`, {
      method: 'PATCH',
      body: JSON.stringify(payload),
    })
  },
  caixetaStatus() {
    return request<CaixetaStatus>('/statements/caixeta')
  },
  /** `ifDue`: the cheap, throttled check made whenever someone opens the app. */
  syncCaixeta(ifDue = false) {
    return request<CaixetaStatus>(`/statements/caixeta/sync${ifDue ? '?if_due=true' : ''}`, {
      method: 'POST',
    })
  },

  // ── Justifying statements (matching) ────────────────────────────────────
  reconcileStatements() {
    return request<ReconcileStatement[]>('/reconciliation/statements')
  },
  reconcileMovements(statementId: number) {
    return request<Movement[]>(`/reconciliation/movements?statement=${statementId}`)
  },
  reconcileMovement(movementId: number) {
    return request<MovementDetail>(`/reconciliation/movements/${movementId}`)
  },
  startMatchRun(importId: number | null) {
    return request<MatchRun>('/reconciliation/runs', {
      method: 'POST',
      body: JSON.stringify({ import_id: importId }),
    })
  },
  matchRun(runId: number) {
    return request<MatchRun>(`/reconciliation/runs/${runId}`)
  },
  activeMatchRun(statementId: number) {
    return request<MatchRun | null>(`/reconciliation/runs?statement=${statementId}`)
  },
  confirmMatch(movementId: number, documentRefs: string[]) {
    return request<MovementDetail>(`/reconciliation/movements/${movementId}/confirm`, {
      method: 'POST',
      body: JSON.stringify({ document_refs: documentRefs }),
    })
  },
  rejectMovement(movementId: number) {
    return request<MovementDetail>(`/reconciliation/movements/${movementId}/reject`, { method: 'POST' })
  },
  rejectMatch(matchId: number) {
    return request<MovementDetail>(`/reconciliation/matches/${matchId}/reject`, { method: 'POST' })
  },
  undoMovement(movementId: number) {
    return request<MovementDetail>(`/reconciliation/movements/${movementId}/undo`, { method: 'POST' })
  },
  reproposeMovement(movementId: number) {
    return request<MovementDetail>(`/reconciliation/movements/${movementId}/repropose`, {
      method: 'POST',
    })
  },
  searchInvoices(q: string) {
    return request<DocumentBrief[]>(`/reconciliation/documents/search?q=${encodeURIComponent(q)}`)
  },
  documentPayments(reference: string) {
    return request<DocumentPayment[]>(`/reconciliation/documents/${reference}/payments`)
  },

  // ── Documents app settings ──────────────────────────────────────────────
  getSettings() {
    return request<WorkspaceSettings>('/documents/settings')
  },
  updateSettings(payload: WorkspaceSettings) {
    return request<WorkspaceSettings>('/documents/settings', {
      method: 'PUT',
      body: JSON.stringify(payload),
    })
  },
}
