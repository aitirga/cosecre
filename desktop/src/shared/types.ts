export type UpdatePhase =
  | 'idle'
  | 'checking'
  | 'up-to-date'
  /** A newer version exists but this build cannot install it itself. */
  | 'available'
  | 'downloading'
  | 'ready'
  | 'error'
  /** Development, or any build with no update feed to read. */
  | 'unsupported'

export interface UpdateState {
  phase: UpdatePhase
  currentVersion: string
  newVersion?: string
  percent?: number
  message?: string
  releaseUrl?: string
  /**
   * Whether this build can replace itself in place. False for an unsigned macOS
   * bundle, which degrades to "download the DMG" instead.
   */
  canSelfInstall: boolean
}

/**
 * What the renderer is handed at startup, synchronously.
 *
 * Tokens have to be readable before the first request goes out, so they cannot
 * arrive over an async channel.
 */
export interface Bootstrap {
  hubUrl: string | null
  tokens: Record<string, string>
  version: string
  platform: NodeJS.Platform
  deviceLabel: string
}

export interface CosecreDesktopApi {
  bootstrap: Bootstrap
  setHubUrl(url: string): Promise<void>
  setToken(key: string, value: string): void
  removeToken(key: string): void
  openExternal(url: string): Promise<void>
  getUpdateState(): Promise<UpdateState>
  checkForUpdates(): Promise<UpdateState>
  applyUpdate(): Promise<void>
  onUpdateState(callback: (state: UpdateState) => void): () => void
}
