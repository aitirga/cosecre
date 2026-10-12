import { mkdir, readFile, rename, writeFile } from 'node:fs/promises'
import { join } from 'node:path'
import { safeStorage } from 'electron'
import type { BrowserCredentialsInput, BrowserCredentialsStatus } from '../../../../frontend/src/browser/contract'

interface StoredCredential { username: string; password: string; automatic: boolean }
export interface LoginCredential { username: string; password: string; automatic: boolean }

/** Passwords never leave the main process through a read/status channel. */
export class BrowserCredentials {
  private path: string
  private records: Record<string, StoredCredential> = {}
  private loaded: Promise<void> | null = null
  private writing: Promise<void> = Promise.resolve()
  constructor(private directory: string) { this.path = join(directory, 'sfera-credentials.json') }
  available(): boolean {
    return safeStorage.isEncryptionAvailable() && !(process.platform === 'linux' && safeStorage.getSelectedStorageBackend() === 'basic_text')
  }
  private load(): Promise<void> {
    this.loaded ??= (async () => {
      try {
        const parsed: unknown = JSON.parse(await readFile(this.path, 'utf8'))
        if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) throw new Error('Invalid credential store')
        this.records = parsed as Record<string, StoredCredential>
      } catch (error) {
        if ((error as NodeJS.ErrnoException).code !== 'ENOENT') throw new Error('No es pot llegir el magatzem segur d’Esfer@.')
      }
    })()
    return this.loaded
  }
  async status(context: string): Promise<BrowserCredentialsStatus> {
    await this.load()
    const value = this.records[context]
    return { username: value?.username ?? '', configured: Boolean(value?.password), automatic: value?.automatic ?? false, encryptionAvailable: this.available() }
  }
  async save(context: string, input: BrowserCredentialsInput): Promise<BrowserCredentialsStatus> {
    await this.load()
    if (!input || typeof input.username !== 'string' || input.username.trim().length > 200 || typeof input.automatic !== 'boolean' || (input.password !== undefined && (typeof input.password !== 'string' || input.password.length > 4096))) throw new Error('Les dades d’accés no són vàlides.')
    if (!this.available()) throw new Error('El dispositiu no disposa d’un magatzem segur. Inicia sessió manualment.')
    const previous = this.records[context]
    const username = input.username.trim()
    if (!username) throw new Error('Introdueix l’usuari de GICAR.')
    if (!input.password && (!previous?.password || previous.username !== username)) throw new Error('Introdueix la contrasenya per a aquest usuari.')
    const password = input.password ? safeStorage.encryptString(input.password).toString('base64') : previous!.password
    const next = { username, password, automatic: input.automatic }
    this.records[context] = next
    try { await this.persist() }
    catch {
      if (this.records[context] === next) { if (previous) this.records[context] = previous; else delete this.records[context] }
      throw new Error('No s’han pogut desar les credencials al dispositiu.')
    }
    return this.status(context)
  }
  async remove(context: string): Promise<BrowserCredentialsStatus> {
    await this.load()
    const previous = this.records[context]
    delete this.records[context]
    try { await this.persist() }
    catch {
      if (!this.records[context] && previous) this.records[context] = previous
      throw new Error('No s’han pogut eliminar les credencials del dispositiu.')
    }
    return this.status(context)
  }
  async login(context: string, force = false): Promise<LoginCredential | null> {
    await this.load()
    const value = this.records[context]
    if (!value || (!value.automatic && !force) || !value.password) return null
    if (!this.available()) throw new Error('El magatzem segur no està disponible; identifica’t manualment.')
    try { return { username: value.username, password: safeStorage.decryptString(Buffer.from(value.password, 'base64')), automatic: true } }
    catch { throw new Error('No es pot desxifrar la contrasenya. Torna-la a desar a Configuració.') }
  }
  private persist(): Promise<void> {
    const snapshot = JSON.stringify(this.records)
    this.writing = this.writing.catch(() => {}).then(async () => {
      await mkdir(this.directory, { recursive: true })
      const temporary = `${this.path}.${process.pid}.tmp`
      await writeFile(temporary, snapshot, { encoding: 'utf8', mode: 0o600 })
      await rename(temporary, this.path)
    })
    return this.writing
  }
}
