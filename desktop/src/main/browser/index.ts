import { createHash, randomUUID } from 'node:crypto'
import { BrowserWindow, WebContentsView, app, dialog, session, type IpcMainInvokeEvent, type WebContents, type DownloadItem, type Event } from 'electron'
import type { BrowserAction, BrowserBounds, BrowserCredentialsInput, BrowserState } from '../../../../frontend/src/browser/contract'
import { portalUrl } from '../../../../frontend/src/browser/url'
import { BrowserCredentials } from './credentials'
import { isGicarLogin, submitSferaLogin } from './sfera-login'
import type { DesktopStore } from '../store'
import { queryPortal, validateQuery } from '../sfera/explorer'
import { readDashboard, selectCentre } from '../sfera/dashboard'
import { SferaInvoices } from '../sfera/invoices'
import { hubClient, reconcileExportItem, runExportItem } from '../sfera/export-runner'
import { diagnoseExport } from '../sfera/diagnostics'
import type { SferaInvoiceBridge } from '../../../../frontend/src/sfera/invoice-bridge'

/** No privilege-bearing preload ever runs in a portal or its login popups. */
// Its fixed data adapter must also run when the native view is hidden.
const preferences = { nodeIntegration: false, contextIsolation: true, sandbox: true, webSecurity: true, allowRunningInsecureContent: false, backgroundThrottling: false }
function navigable(value: string): boolean {
  try {
    const u = new URL(value)
    return !u.username && !u.password && (u.protocol === 'https:' || (u.protocol === 'http:' && ['localhost', '127.0.0.1', '[::1]'].includes(u.hostname)))
  } catch { return false }
}
export class EmbeddedBrowser {
  private view: WebContentsView | null = null
  private popups = new Set<BrowserWindow>()
  private id = ''
  private initialUrl = ''
  private credentials = new BrowserCredentials(app.getPath('userData'))
  private context = ''
  private login: BrowserState['login'] = 'manual'
  private loginMessage: string | null = null
  private attemptedLogin = false
  private error: string | null = null
  private epoch = 0
  private attached = false
  private downloads = new Set<DownloadItem>()
  private downloadOwners = new Set<number>()
  private removeDownloadHandler: (() => void) | null = null
  private querying = false
  private invoices = new SferaInvoices()
  constructor(private window: BrowserWindow, private store: DesktopStore, private notify: (state: BrowserState) => void) {
    window.webContents.on('did-start-navigation', (details) => { if (details.isMainFrame && !details.isSameDocument) this.dispose() })
    window.on('closed', () => this.dispose())
  }
  assertSender(event: IpcMainInvokeEvent): void {
    if (event.sender !== this.window.webContents || event.senderFrame !== this.window.webContents.mainFrame) throw new Error('Origen no autoritzat.')
  }
  private async credentialContext(tool: unknown): Promise<string> {
    if (tool !== 'sfera') throw new Error('Eina desconeguda.')
    const hub = this.store.hubUrl
    const token = this.store.tokens['cosecre.accessToken']
    if (!hub || !token) throw new Error('Cal iniciar sessió a Cosecre.')
    const root = hub.replace(/\/$/, '').replace(/\/api\/v1$/, '') + '/api/v1'
    const response = await fetch(root + '/auth/me', { headers: { Authorization: `Bearer ${token}` }, redirect: 'error', signal: AbortSignal.timeout(10000) })
    if (!response.ok) throw new Error('No es pot verificar el compte.')
    const user = await response.json() as { id: number; role?: string; is_admin?: boolean }
    if (!['admin', 'administratiu'].includes(user.role ?? (user.is_admin ? 'admin' : 'administratiu')) || !Number.isSafeInteger(user.id)) throw new Error('Compte no autoritzat per configurar l’accés.')
    if (hub !== this.store.hubUrl || token !== this.store.tokens['cosecre.accessToken']) throw new Error('El compte ha canviat.')
    return createHash('sha256').update(JSON.stringify([root, user.id, tool])).digest('hex')
  }
  async credentialsStatus(tool: unknown) { return this.credentials.status(await this.credentialContext(tool)) }
  async saveCredentials(tool: unknown, input: BrowserCredentialsInput) {
    const context = await this.credentialContext(tool)
    const status = await this.credentials.save(context, input)
    if (status.automatic && context === this.context && this.view) { this.attemptedLogin = false; void this.identify(this.view.webContents) }
    return status
  }
  async removeCredentials(tool: unknown) { return this.credentials.remove(await this.credentialContext(tool)) }
  private async identify(wc: WebContents, force = false): Promise<void> {
    if (this.attemptedLogin || !isGicarLogin(wc.getURL())) return
    this.attemptedLogin = true
    const id = this.id
    try {
      const credential = await this.credentials.login(this.context, force)
      if (!credential || id !== this.id || wc.isDestroyed()) return
      const submitted = await submitSferaLogin(wc, credential)
      if (id !== this.id) return
      this.login = submitted ? 'submitted' : 'error'
      this.loginMessage = submitted ? 'Identificació enviada a GICAR. Completa qualsevol verificació addicional al portal.' : 'El formulari de GICAR ha canviat. Identifica’t manualment.'
    } catch {
      if (id !== this.id) return
      this.login = 'error'; this.loginMessage = 'No es pot utilitzar l’accés desat. Revisa la configuració o identifica’t manualment.'
    }
    if (this.view?.webContents === wc) this.notify(this.state(id))
  }
  async open(tool: unknown): Promise<BrowserState> {
    if (tool !== 'sfera') throw new Error('Eina desconeguda.')
    // A hidden portal retained between Navegador and Resum i dades keeps the
    // selected centre and its private request headers in the same sandbox.
    if (this.view && !this.view.webContents.isDestroyed()) {
      const epoch = this.epoch, hub = this.store.hubUrl, token = this.store.tokens['cosecre.accessToken']
      const context = await this.credentialContext(tool)
      const root = hub!.replace(/\/$/, '').replace(/\/api\/v1$/, '') + '/api/v1'
      const response = await fetch(root + '/apps/cosecre-sfera/settings', { headers: { Authorization: `Bearer ${token}` }, redirect: 'error', signal: AbortSignal.timeout(10000) })
      if (!response.ok) throw new Error('No es pot verificar la configuració d’Esfer@.')
      const bundle = await response.json() as { settings?: { access_url?: string } }
      if (epoch !== this.epoch || hub !== this.store.hubUrl || token !== this.store.tokens['cosecre.accessToken']) throw new Error('El context de la sessió ha canviat.')
      if (context === this.context && portalUrl(bundle.settings?.access_url) === this.initialUrl) return this.state(this.id)
    }
    this.dispose()
    const epoch = this.epoch
    const hub = this.store.hubUrl
    const token = this.store.tokens['cosecre.accessToken']
    if (!hub || !token) throw new Error('Cal iniciar sessió a Cosecre.')
    const root = hub.replace(/\/$/, '').replace(/\/api\/v1$/, '') + '/api/v1'
    const get = async (path: string) => {
      const response = await fetch(root + path, { headers: { Authorization: `Bearer ${token}` }, redirect: 'error', signal: AbortSignal.timeout(10000) })
      if (!response.ok) throw new Error('No es pot verificar el compte o la configuració d’Esfer@. Torna a iniciar sessió si ha caducat.')
      return response.json() as Promise<{ id?: number; role?: string; is_admin?: boolean; settings?: { access_url?: string } }>
    }
    const [user, bundle] = await Promise.all([get('/auth/me'), get('/apps/cosecre-sfera/settings')])
    if (epoch !== this.epoch || hub !== this.store.hubUrl || token !== this.store.tokens['cosecre.accessToken']) throw new Error('El context de la sessió ha canviat.')
    const role = user.role ?? (user.is_admin ? 'admin' : 'administratiu')
    if (!['admin', 'administratiu'].includes(role) || !Number.isSafeInteger(user.id)) throw new Error('Compte no autoritzat.')
    this.initialUrl = portalUrl(bundle.settings?.access_url)
    this.context = createHash('sha256').update(JSON.stringify([root, user.id, tool])).digest('hex')
    try {
      const credentialStatus = await this.credentials.status(this.context)
      this.login = credentialStatus.automatic && credentialStatus.configured ? 'waiting' : 'manual'
      this.loginMessage = this.login === 'waiting' ? 'Accés automàtic activat per a GICAR.' : null
    } catch {
      this.login = 'error'; this.loginMessage = 'No es pot llegir l’accés personal. Pots identificar-te manualment.'
    }
    if (epoch !== this.epoch) throw new Error('El context ha canviat.')
    const partition = 'persist:cosecre-browser-' + this.context
    const ses = session.fromPartition(partition)
    ses.setPermissionRequestHandler((_wc, _permission, respond) => respond(false))
    ses.setPermissionCheckHandler(() => false)
    this.view = new WebContentsView({ webPreferences: { ...preferences, session: ses } })
    this.id = randomUUID()
    const wc = this.view.webContents
    this.secure(wc)
    const publish = () => { if (this.view?.webContents === wc) this.notify(this.state(this.id)) }
    wc.on('did-start-loading', () => { this.error = null; publish() })
    wc.on('did-stop-loading', publish)
    wc.on('did-finish-load', () => { void this.identify(wc) })
    wc.on('did-navigate', publish)
    wc.on('did-navigate-in-page', publish)
    wc.on('page-title-updated', publish)
    wc.on('did-fail-load', (_event, code, _description, _url, mainFrame) => {
      if (mainFrame && code !== -3) { this.error = `No s'ha pogut carregar el portal (${code}).`; publish() }
    })
    wc.on('render-process-gone', () => { this.error = 'El navegador s’ha aturat. Torna a obrir Esfer@.'; publish() })
    const download = (_event: Event, item: DownloadItem, contents: WebContents) => {
      if (!this.downloadOwners.has(contents.id)) return
      // Electron shows its native Save dialog; no unattended file writes.
      this.downloads.add(item)
      item.setSaveDialogOptions({ title: 'Desar fitxer d’Esfer@' })
      item.once('done', (_event, state) => { this.downloads.delete(item); if (state === 'interrupted' && this.view?.webContents === wc) { this.error = 'La descàrrega no s’ha completat.'; publish() } })
    }
    ses.on('will-download', download)
    this.removeDownloadHandler = () => ses.removeListener('will-download', download)
    void wc.loadURL(this.initialUrl).catch(() => {})
    return this.state(this.id)
  }
  private secure(wc: WebContents): void {
    this.downloadOwners.add(wc.id)
    const check = (event: { preventDefault(): void }, url: string) => { if (!navigable(url)) event.preventDefault() }
    wc.on('will-navigate', check)
    wc.on('will-redirect', check)
    wc.on('will-frame-navigate', (event) => check(event, event.url))
    wc.setWindowOpenHandler(({ url }) => {
      if ((url !== 'about:blank' && !navigable(url)) || this.popups.size >= 4) return { action: 'deny' }
      return { action: 'allow', overrideBrowserWindowOptions: {
        parent: this.window, width: 900, height: 700, autoHideMenuBar: true,
        webPreferences: { ...preferences, session: wc.session, preload: undefined },
      } }
    })
    wc.on('did-create-window', (popup) => {
      this.popups.add(popup)
      popup.setMenu(null)
      this.secure(popup.webContents)
      popup.on('closed', () => this.popups.delete(popup))
    })
    wc.on('will-attach-webview', (event) => event.preventDefault())
  }
  private contents(id: unknown): WebContents {
    if (id !== this.id || !this.view || this.view.webContents.isDestroyed()) throw new Error('La sessió del navegador ja no és activa.')
    return this.view.webContents
  }
  state(id: unknown): BrowserState {
    const wc = this.contents(id)
    return { id: this.id, url: wc.getURL(), title: wc.getTitle(), loading: wc.isLoading(), canGoBack: wc.navigationHistory.canGoBack(), canGoForward: wc.navigationHistory.canGoForward(), error: this.error, login: this.login, loginMessage: this.loginMessage }
  }
  layout(id: unknown, bounds: BrowserBounds | null): void {
    // Geometry messages can arrive after route/account teardown. They must not
    // change a newer view or surface spurious errors during logout.
    if (id !== this.id || !this.view) return
    const wc = this.contents(id)
    if (bounds === null) {
      if (this.attached) this.window.contentView.removeChildView(this.view!)
      this.attached = false
      for (const popup of this.popups) popup.hide()
      return
    }
    if (!bounds || typeof bounds !== 'object' || !['x','y','width','height'].every((key) => Number.isFinite(bounds[key as keyof BrowserBounds]))) throw new Error('Dimensions no vàlides.')
    const zoom = this.window.webContents.getZoomFactor()
    const [width, height] = this.window.getContentSize()
    const x = Math.max(0, Math.min(width, Math.round(bounds.x * zoom)))
    const y = Math.max(0, Math.min(height, Math.round(bounds.y * zoom)))
    const w = Math.max(0, Math.min(width - x, Math.round(bounds.width * zoom)))
    const h = Math.max(0, Math.min(height - y, Math.round(bounds.height * zoom)))
    if (w < 1 || h < 1) { this.layout(id, null); return }
    this.view!.setBounds({ x, y, width: w, height: h })
    if (!this.attached) { this.window.contentView.addChildView(this.view!); this.attached = true }
    // Hidden popups must not reappear over a different route or a dialog.
    if (!wc.isDestroyed()) for (const popup of this.popups) if (!popup.isVisible()) popup.show()
  }
  async command(id: unknown, action: BrowserAction): Promise<BrowserState> {
    const wc = this.contents(id)
    switch (action) {
      case 'login': this.attemptedLogin = false; void this.identify(wc, true); break
      case 'back': if (wc.navigationHistory.canGoBack()) wc.navigationHistory.goBack(); break
      case 'forward': if (wc.navigationHistory.canGoForward()) wc.navigationHistory.goForward(); break
      case 'reload': wc.reload(); break
      case 'home': void wc.loadURL(this.initialUrl).catch(() => {}); break
      case 'clear-session': {
        const answer = await dialog.showMessageBox(this.window, { type: 'question', message: 'Esborrar la sessió local d’Esfer@?', detail: 'Caldrà tornar a iniciar sessió al portal.', buttons: ['Cancel·lar', 'Esborrar'], defaultId: 0, cancelId: 0 })
        if (answer.response !== 1) break
        this.contents(id)
        for (const popup of this.popups) popup.destroy()
        this.attemptedLogin = true
        this.login = 'manual'
        this.loginMessage = 'Sessió esborrada. Pots identificar-te manualment o prémer Identificar-me.'
        wc.stop()
        await wc.loadURL('about:blank')
        await wc.session.clearStorageData()
        await wc.session.clearCache()
        await wc.session.clearAuthCache()
        this.contents(id)
        void wc.loadURL(this.initialUrl).catch(() => {})
        break
      }
      default: throw new Error('Acció desconeguda.')
    }
    return this.state(id)
  }
  close(id: unknown): void { if (id === this.id) this.dispose() }
  release(tool: unknown): void {
    if (tool !== 'sfera') throw new Error('Eina desconeguda.')
    this.dispose()
  }
  async query(input: unknown) {
    const query = validateQuery(input)
    return this.withPortal((wc,url,valid)=>queryPortal(wc,url,query,valid))
  }
  async dashboard(input: unknown) {
    const raw = input && typeof input === 'object' && !Array.isArray(input) ? input as Record<string, unknown> : {}
    if (Object.keys(raw).some(k => k !== 'budgetId') || (raw.budgetId !== undefined && (!Number.isSafeInteger(raw.budgetId) || Number(raw.budgetId) <= 0))) throw new Error('Consulta no vàlida.')
    return this.withPortal((wc,url,valid)=>readDashboard(wc,url,raw.budgetId === undefined ? {} : { budgetId: Number(raw.budgetId) },valid))
  }
  async dashboardCentre(code: unknown) { return this.withPortal((wc,url,valid)=>selectCentre(wc,url,code,valid)) }
  async invoiceCatalog(budgetId?:number) { return this.withPortal((wc,url,valid)=>this.invoices.catalog(wc,url,valid,budgetId)) }
  async invoicePrepare(input: Parameters<SferaInvoiceBridge['prepare']>[0]) { return this.withPortal((wc,url,valid)=>this.invoices.prepare(wc,url,valid,input)) }
  async invoiceCreate(id:unknown) { return this.withPortal((wc,url,valid)=>this.invoices.create(wc,url,valid,id)) }
  private hub() {
    const hub = this.store.hubUrl, token = this.store.tokens['cosecre.accessToken']
    if (!hub || !token) throw new Error('Cal iniciar sessió a Cosecre.')
    return hubClient(hub.replace(/\/$/, '').replace(/\/api\/v1$/, '') + '/api/v1', token)
  }
  async exportRun(planId: unknown, itemId: unknown) { const hub = this.hub(); return this.withPortal((wc, url, valid) => runExportItem(wc, url, valid, hub, planId, itemId)) }
  async exportReconcile(planId: unknown, itemId: unknown) { const hub = this.hub(); return this.withPortal((wc, url, valid) => reconcileExportItem(wc, url, valid, hub, planId, itemId)) }
  async exportDiagnose() { const hub = this.hub(); return this.withPortal((wc, url, valid) => diagnoseExport(wc, url, valid, hub)) }
  private async withPortal<T>(execute:(wc:WebContents,url:string,valid:()=>boolean)=>Promise<T>):Promise<T> {
    if (this.querying) throw new Error('Ja hi ha una consulta en curs.')
    this.querying = true
    const epoch = this.epoch, hub = this.store.hubUrl, token = this.store.tokens['cosecre.accessToken']
    const valid = () => epoch === this.epoch && hub === this.store.hubUrl && token === this.store.tokens['cosecre.accessToken']
    try {
      const context = await this.credentialContext('sfera')
      if (!valid() || context !== this.context || !this.view) throw new Error('Obre Esfer@ al navegador, identifica’t i selecciona un centre.')
      const root = hub!.replace(/\/$/, '').replace(/\/api\/v1$/, '') + '/api/v1'
      const response = await fetch(root + '/apps/cosecre-sfera/settings', { headers: { Authorization: `Bearer ${token}` }, redirect: 'error', signal: AbortSignal.timeout(10000) })
      if (!response.ok) throw new Error('No es pot verificar la configuració d’Esfer@.')
      const settings = await response.json() as { settings?: { access_url?: string } }
      if (!valid() || portalUrl(settings.settings?.access_url) !== this.initialUrl) throw new Error('La configuració ha canviat. Torna a obrir el navegador.')
      return await execute(this.view.webContents,this.initialUrl,valid)
    } finally { this.querying = false }
  }
  dispose(): void {
    this.epoch++
    this.invoices.clear()
    for (const popup of this.popups) popup.destroy()
    this.popups.clear()
    for (const download of this.downloads) download.cancel()
    this.downloads.clear()
    this.removeDownloadHandler?.(); this.removeDownloadHandler = null
    this.downloadOwners.clear()
    if (this.view) {
      if (this.attached && !this.window.isDestroyed()) this.window.contentView.removeChildView(this.view)
      if (!this.view.webContents.isDestroyed()) this.view.webContents.close()
    }
    this.view = null; this.attached = false; this.error = null; this.id = ''; this.context = ''; this.attemptedLogin = false; this.login = 'manual'; this.loginMessage = null
  }
}
