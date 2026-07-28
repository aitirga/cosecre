import { mkdir, readFile, rename, writeFile } from 'node:fs/promises'
import { dirname, join } from 'node:path'

interface Persisted {
  hubUrl: string | null
  /**
   * Session tokens, keyed by hub URL then by token name.
   *
   * Namespacing by hub is what stops a session following the user to a
   * different server when they switch — the tokens of one hub are meaningless
   * to another, and sending them there would leak them.
   */
  tokensByHub: Record<string, Record<string, string>>
}

const EMPTY: Persisted = { hubUrl: null, tokensByHub: {} }

/**
 * The desktop app's own state: which hub it points at, and the session for each
 * hub it has signed into.
 *
 * Tokens live here rather than in the renderer's `localStorage` because a
 * packaged renderer is loaded from `file://`, where web storage is not
 * something to rely on.
 */
export class DesktopStore {
  #path: string
  #value: Persisted = { ...EMPTY }
  /** Serialises writes so two quick token updates cannot interleave. */
  #writing: Promise<void> = Promise.resolve()

  constructor(userDataDir: string) {
    this.#path = join(userDataDir, 'cosecre-desktop.json')
  }

  async load(): Promise<void> {
    try {
      const parsed = JSON.parse(await readFile(this.#path, 'utf8')) as Partial<Persisted>
      this.#value = {
        hubUrl: typeof parsed.hubUrl === 'string' ? parsed.hubUrl : null,
        tokensByHub:
          parsed.tokensByHub && typeof parsed.tokensByHub === 'object' ? parsed.tokensByHub : {},
      }
    } catch {
      // Missing or corrupt: start clean rather than refuse to launch. The worst
      // case is one more sign-in.
      this.#value = { ...EMPTY }
    }
  }

  get hubUrl(): string | null {
    return this.#value.hubUrl
  }

  get tokens(): Record<string, string> {
    const hub = this.#value.hubUrl
    return hub ? { ...(this.#value.tokensByHub[hub] ?? {}) } : {}
  }

  setHubUrl(url: string): void {
    this.#value.hubUrl = url
    this.#persist()
  }

  setToken(key: string, value: string): void {
    const hub = this.#value.hubUrl
    if (!hub) return
    this.#value.tokensByHub[hub] = { ...(this.#value.tokensByHub[hub] ?? {}), [key]: value }
    this.#persist()
  }

  removeToken(key: string): void {
    const hub = this.#value.hubUrl
    if (!hub) return
    const existing = { ...(this.#value.tokensByHub[hub] ?? {}) }
    delete existing[key]
    this.#value.tokensByHub[hub] = existing
    this.#persist()
  }

  /** Fire-and-forget, but ordered: callers never wait on disk. */
  #persist(): void {
    const snapshot = JSON.stringify(this.#value, null, 2)
    this.#writing = this.#writing
      .then(async () => {
        await mkdir(dirname(this.#path), { recursive: true })
        // Temp file + rename, so a crash mid-write cannot leave a truncated
        // file that would lose every stored session.
        const temp = `${this.#path}.${process.pid}.tmp`
        await writeFile(temp, snapshot, 'utf8')
        await rename(temp, this.#path)
      })
      .catch(() => {
        // A store that cannot be written still works for this session.
      })
  }
}
