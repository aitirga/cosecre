import type { BrowserBridge, BrowserState } from '../../../frontend/src/browser/contract'
import { contextBridge, ipcRenderer, webUtils } from 'electron'
import type {
  AddFilesResult,
  ConverterStatus,
  HistoryEntry,
  Job,
  PrinterInfo,
  PrintBridge,
  PrintOptions,
  Settings,
} from '@print/contract'

import { IPC } from '../shared/ipc.js'
import type { Bootstrap, CosecreDesktopApi, UpdateState } from '../shared/types.js'

// Read synchronously at preload time. The renderer needs the hub URL and the
// stored session before it makes its first request, and awaiting an async
// channel there would mean rendering a signed-out app for a frame.
const bootstrap = ipcRenderer.sendSync(IPC.bootstrap) as Bootstrap

const print: PrintBridge = {
  listPrinters: () => ipcRenderer.invoke(IPC.printListPrinters) as Promise<PrinterInfo[]>,
  refreshPrinters: () => ipcRenderer.invoke(IPC.printRefreshPrinters) as Promise<PrinterInfo[]>,
  getConverterStatus: () =>
    ipcRenderer.invoke(IPC.printConverterStatus) as Promise<ConverterStatus>,

  pickFiles: () => ipcRenderer.invoke(IPC.printPickFiles) as Promise<AddFilesResult>,
  addFiles: (paths) => ipcRenderer.invoke(IPC.printAddFiles, paths) as Promise<AddFilesResult>,

  // Electron removed `File.path` in v32, so a dropped file's real location has
  // to come from `webUtils`, which only exists here in the preload.
  getPathForFile: (file) => webUtils.getPathForFile(file),

  getJobs: () => ipcRenderer.invoke(IPC.printGetJobs) as Promise<Job[]>,
  updateJobOptions: (jobId, options: Partial<PrintOptions>) =>
    ipcRenderer.invoke(IPC.printUpdateJobOptions, jobId, options) as Promise<Job | undefined>,
  applyOptionsToAll: (options: Partial<PrintOptions>) =>
    ipcRenderer.invoke(IPC.printApplyOptionsToAll, options) as Promise<Job[]>,
  removeJob: (jobId) => ipcRenderer.invoke(IPC.printRemoveJob, jobId) as Promise<void>,
  clearFinished: () => ipcRenderer.invoke(IPC.printClearFinished) as Promise<void>,

  printJobs: (jobIds) => ipcRenderer.invoke(IPC.printJobs, jobIds) as Promise<void>,
  cancelJob: (jobId) => ipcRenderer.invoke(IPC.printCancelJob, jobId) as Promise<void>,
  retryJob: (jobId) => ipcRenderer.invoke(IPC.printRetryJob, jobId) as Promise<void>,

  readPrintable: (jobId) =>
    ipcRenderer.invoke(IPC.printReadPrintable, jobId) as Promise<Uint8Array>,
  reportPageCount: (jobId, pageCount) =>
    ipcRenderer.invoke(IPC.printReportPageCount, jobId, pageCount) as Promise<void>,

  getHistory: () => ipcRenderer.invoke(IPC.printGetHistory) as Promise<HistoryEntry[]>,
  clearHistory: () => ipcRenderer.invoke(IPC.printClearHistory) as Promise<void>,

  getSettings: () => ipcRenderer.invoke(IPC.printGetSettings) as Promise<Settings>,
  setSettings: (patch) => ipcRenderer.invoke(IPC.printSetSettings, patch) as Promise<Settings>,

  onJobUpdate: (callback) => {
    const listener = (_event: unknown, jobs: Job[]): void => callback(jobs)
    ipcRenderer.on(IPC.printJobsChanged, listener)
    return () => ipcRenderer.removeListener(IPC.printJobsChanged, listener)
  },
  onHistoryUpdate: (callback) => {
    const listener = (_event: unknown, entries: HistoryEntry[]): void => callback(entries)
    ipcRenderer.on(IPC.printHistoryChanged, listener)
    return () => ipcRenderer.removeListener(IPC.printHistoryChanged, listener)
  },
}

const browser: BrowserBridge = {
  credentialsStatus: (tool) => ipcRenderer.invoke(IPC.browserCredentialsStatus, tool),
  saveCredentials: (tool, input) => ipcRenderer.invoke(IPC.browserCredentialsSave, tool, input),
  removeCredentials: (tool) => ipcRenderer.invoke(IPC.browserCredentialsRemove, tool),
  open: (tool) => ipcRenderer.invoke(IPC.browserOpen, tool),
  layout: (id, bounds) => ipcRenderer.invoke(IPC.browserLayout, id, bounds),
  command: (id, action) => ipcRenderer.invoke(IPC.browserCommand, id, action),
  state: (id) => ipcRenderer.invoke(IPC.browserState, id),
  close: (id) => ipcRenderer.invoke(IPC.browserClose, id),
  release: (tool) => ipcRenderer.invoke(IPC.browserRelease, tool),
  onState: (callback) => {
    const listener = (_event: unknown, state: BrowserState) => callback(state)
    ipcRenderer.on(IPC.browserChanged, listener)
    return () => ipcRenderer.removeListener(IPC.browserChanged, listener)
  },
}

const api: CosecreDesktopApi = {
  bootstrap,

  setHubUrl: (url) => ipcRenderer.invoke(IPC.setHubUrl, url) as Promise<void>,
  // Fire-and-forget: token writes must not block a response the app already has.
  setToken: (key, value) => ipcRenderer.send(IPC.setToken, key, value),
  removeToken: (key) => ipcRenderer.send(IPC.removeToken, key),
  openExternal: (url) => ipcRenderer.invoke(IPC.openExternal, url) as Promise<void>,

  getUpdateState: () => ipcRenderer.invoke(IPC.getUpdateState) as Promise<UpdateState>,
  checkForUpdates: () => ipcRenderer.invoke(IPC.checkForUpdates) as Promise<UpdateState>,
  applyUpdate: () => ipcRenderer.invoke(IPC.applyUpdate) as Promise<void>,

  onUpdateState: (callback) => {
    const listener = (_event: unknown, state: UpdateState): void => callback(state)
    ipcRenderer.on(IPC.updateStateChanged, listener)
    return () => ipcRenderer.removeListener(IPC.updateStateChanged, listener)
  },

  print,
  browser,
  sferaData: { query: (input) => ipcRenderer.invoke(IPC.sferaQuery, input) },
  sferaDashboard: {
    load: (input) => ipcRenderer.invoke(IPC.sferaDashboard, input),
    selectCentre: (code) => ipcRenderer.invoke(IPC.sferaDashboardCentre, code),
  },
  sferaInvoices: {
    catalog: (budgetId)=>ipcRenderer.invoke(IPC.sferaInvoiceCatalog,budgetId),
    prepare: (input)=>ipcRenderer.invoke(IPC.sferaInvoicePrepare,input),
    create: (id)=>ipcRenderer.invoke(IPC.sferaInvoiceCreate,id),
  },
  sferaExport: {
    run: (planId, itemId) => ipcRenderer.invoke(IPC.sferaExportRun, planId, itemId),
    reconcile: (planId, itemId) => ipcRenderer.invoke(IPC.sferaExportReconcile, planId, itemId),
    diagnose: () => ipcRenderer.invoke(IPC.sferaExportDiagnose),
  },
}

contextBridge.exposeInMainWorld('cosecreDesktop', api)
