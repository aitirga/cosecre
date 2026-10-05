import { existsSync } from 'node:fs'
import { hostname } from 'node:os'
import { join } from 'node:path'
import { fileURLToPath } from 'node:url'
import { BrowserWindow, app, ipcMain, nativeTheme, shell } from 'electron'

import { IPC } from '../shared/ipc.js'
import type { Bootstrap } from '../shared/types.js'
import { buildMenu } from './menu.js'
import { startPrinting, type PrintService } from './print/index.js'
import { DesktopStore } from './store.js'
import { Updater } from './updater.js'

const dirname = fileURLToPath(new URL('.', import.meta.url))

let mainWindow: BrowserWindow | null = null
let store: DesktopStore | null = null
let updater: Updater | null = null
let printing: PrintService | null = null

function loadRenderer(window: BrowserWindow): void {
  const devServerUrl = process.env['ELECTRON_RENDERER_URL']
  if (devServerUrl) {
    void window.loadURL(devServerUrl)
  } else {
    void window.loadFile(join(dirname, '../renderer/index.html'))
  }
}

function createWindow(): BrowserWindow {
  const window = new BrowserWindow({
    width: 1280,
    height: 840,
    minWidth: 900,
    minHeight: 600,
    show: false,
    title: 'Cosecre',
    // Matches --surface-1 in the shared theme, so the first paint is not a
    // white flash against the blue-tinted UI.
    backgroundColor: '#f5f9fe',
    titleBarStyle: process.platform === 'darwin' ? 'hiddenInset' : 'default',
    webPreferences: {
      preload: join(dirname, '../preload/index.mjs'),
      contextIsolation: true,
      nodeIntegration: false,
      // The preload is an ES module, which Electron will not load into a
      // sandboxed renderer. Context isolation is what actually keeps Node out
      // of the page, and it stays on.
      sandbox: false,
    },
  })

  window.on('ready-to-show', () => window.show())

  // Anything that is not the app itself belongs in the user's browser. Without
  // this, an external link would open a chrome-less Electron window with no way
  // back and no address bar to check.
  window.webContents.setWindowOpenHandler(({ url }) => {
    void shell.openExternal(url)
    return { action: 'deny' }
  })

  // Same for in-place navigation: the renderer is the app, and a hub that
  // returned an HTML redirect must not be able to replace it.
  window.webContents.on('will-navigate', (event, url) => {
    const current = window.webContents.getURL()
    if (url.split('#')[0] !== current.split('#')[0]) {
      event.preventDefault()
      void shell.openExternal(url)
    }
  })

  loadRenderer(window)
  return window
}

app.whenReady().then(async () => {
  app.setName('Cosecre')

  // The UI is a single light theme. Pinning the native theme keeps the widgets
  // Chromium draws itself — <select> popups, form controls, the macOS traffic
  // lights — light too, instead of following a dark system setting.
  nativeTheme.themeSource = 'light'

  // A packaged build takes its icon from the bundle, but `npm run dev` would
  // otherwise sit in the Dock as a generic Electron diamond.
  if (!app.isPackaged && process.platform === 'darwin') {
    const icon = join(dirname, '../../build/icon.png')
    if (existsSync(icon)) app.dock?.setIcon(icon)
  }

  store = new DesktopStore(app.getPath('userData'))
  await store.load()

  updater = new Updater({
    onState: (state) => mainWindow?.webContents.send(IPC.updateStateChanged, state),
  })
  // Resolved before the window exists, so the renderer's first read of the
  // update state is already the final answer.
  await updater.init()

  registerIpc()
  printing = await startPrinting(app.getPath('userData'), () => mainWindow)
  buildMenu({
    onCheckForUpdates: () => void updater?.check(),
    onReload: () => mainWindow && loadRenderer(mainWindow),
  })

  mainWindow = createWindow()

  app.on('activate', () => {
    if (BrowserWindow.getAllWindows().length === 0) mainWindow = createWindow()
  })
})

app.on('window-all-closed', () => {
  if (process.platform !== 'darwin') app.quit()
})

app.on('before-quit', () => {
  updater?.dispose()
  void printing?.dispose()
})

function registerIpc(): void {
  // Synchronous: the renderer has to attach a token to its very first request,
  // so the hub URL and the stored session cannot arrive over a promise.
  ipcMain.on(IPC.bootstrap, (event) => {
    const bootstrap: Bootstrap = {
      hubUrl: store?.hubUrl ?? null,
      tokens: store?.tokens ?? {},
      version: app.getVersion(),
      platform: process.platform,
      deviceLabel: hostname(),
    }
    event.returnValue = bootstrap
  })

  ipcMain.handle(IPC.setHubUrl, (_event, url: string) => {
    store?.setHubUrl(url)
    // Reload from the entry point rather than in place: the renderer caches the
    // hub URL, the API base and the session at startup, and a fresh load is the
    // only way to be sure none of the old hub's state survives.
    if (mainWindow) loadRenderer(mainWindow)
  })

  ipcMain.on(IPC.setToken, (_event, key: string, value: string) => store?.setToken(key, value))
  ipcMain.on(IPC.removeToken, (_event, key: string) => store?.removeToken(key))

  ipcMain.handle(IPC.openExternal, async (_event, url: string) => {
    // Only ever hand the OS a web URL — `shell.openExternal` will happily run a
    // `file:` or custom-scheme handler otherwise.
    if (/^https?:\/\//i.test(url)) await shell.openExternal(url)
  })

  ipcMain.handle(IPC.getUpdateState, () => updater?.get())
  ipcMain.handle(IPC.checkForUpdates, () => updater?.check())
  ipcMain.handle(IPC.applyUpdate, () => updater?.apply())
}
