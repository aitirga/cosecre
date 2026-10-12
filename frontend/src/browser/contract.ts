/** Browser capabilities with a private GICAR adapter. No arbitrary script execution, filesystem or hub-token API. */
export interface BrowserState {
  id: string
  url: string
  title: string
  loading: boolean
  canGoBack: boolean
  canGoForward: boolean
  error: string | null
  login: 'manual' | 'waiting' | 'submitted' | 'error'
  loginMessage: string | null
}
export interface BrowserBounds { x: number; y: number; width: number; height: number }
export type BrowserAction = 'back' | 'forward' | 'reload' | 'home' | 'clear-session' | 'login'
export interface BrowserCredentialsStatus {
  username: string
  configured: boolean
  automatic: boolean
  encryptionAvailable: boolean
}
export interface BrowserCredentialsInput { username: string; password?: string; automatic: boolean }
export interface BrowserBridge {
  credentialsStatus(tool: 'sfera'): Promise<BrowserCredentialsStatus>
  saveCredentials(tool: 'sfera', input: BrowserCredentialsInput): Promise<BrowserCredentialsStatus>
  removeCredentials(tool: 'sfera'): Promise<BrowserCredentialsStatus>
  /** Main verifies the account and loads the configured URL directly from the hub. */
  open(tool: 'sfera'): Promise<BrowserState>
  layout(id: string, bounds: BrowserBounds | null): Promise<void>
  command(id: string, action: BrowserAction): Promise<BrowserState>
  state(id: string): Promise<BrowserState>
  close(id: string): Promise<void>
  /** Release an active or pending tool session when leaving its views. */
  release(tool: 'sfera'): Promise<void>
  onState(callback: (state: BrowserState) => void): () => void
}
