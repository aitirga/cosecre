import { dialog, ipcMain, type BrowserWindow } from 'electron'
import type { AddFilesResult, PrinterInfo, PrintOptions, Settings } from '@print/contract'

import { IPC } from '../../shared/ipc.js'
import { resolveLibreOffice } from './convert/libreoffice.js'
import { getDriver } from './printing/driver.js'
import type { Scheduler } from './queue/scheduler.js'
import type { HistoryStore } from './store/history.js'
import type { SettingsStore } from './store/settings.js'
import { log } from './util/log.js'

export interface PrintIpcContext {
  scheduler: Scheduler
  settings: SettingsStore
  history: HistoryStore
  getWindow(): BrowserWindow | null
}

export function registerPrintIpc(ctx: PrintIpcContext): void {
  const { scheduler, settings, history } = ctx

  let printerCache: PrinterInfo[] = []

  const loadPrinters = async (): Promise<PrinterInfo[]> => {
    const driver = await getDriver()
    try {
      printerCache = await driver.listPrinters()
    } catch (error) {
      log.error('Listing printers failed', error)
      throw error
    }
    return printerCache
  }

  ipcMain.handle(IPC.printListPrinters, async () =>
    printerCache.length > 0 ? printerCache : loadPrinters(),
  )
  ipcMain.handle(IPC.printRefreshPrinters, () => loadPrinters())

  ipcMain.handle(IPC.printConverterStatus, () =>
    resolveLibreOffice(settings.get().libreOfficePath),
  )

  ipcMain.handle(IPC.printPickFiles, async (): Promise<AddFilesResult> => {
    const window = ctx.getWindow()
    const result = window
      ? await dialog.showOpenDialog(window, openDialogOptions)
      : await dialog.showOpenDialog(openDialogOptions)

    if (result.canceled || result.filePaths.length === 0) {
      return { jobs: [], rejected: [] }
    }
    return scheduler.addFiles(result.filePaths)
  })

  ipcMain.handle(IPC.printAddFiles, (_event, paths: unknown) => {
    if (!Array.isArray(paths)) return { jobs: [], rejected: [] } satisfies AddFilesResult
    return scheduler.addFiles(paths.filter((p): p is string => typeof p === 'string'))
  })

  ipcMain.handle(IPC.printGetJobs, () => scheduler.list())

  ipcMain.handle(IPC.printUpdateJobOptions, (_event, id: string, patch: Partial<PrintOptions>) =>
    scheduler.updateOptions(id, patch),
  )

  ipcMain.handle(IPC.printApplyOptionsToAll, (_event, patch: Partial<PrintOptions>) =>
    scheduler.applyOptionsToAll(patch),
  )

  ipcMain.handle(IPC.printRemoveJob, (_event, id: string) => scheduler.remove(id))
  ipcMain.handle(IPC.printClearFinished, () => scheduler.clearFinished())

  ipcMain.handle(IPC.printJobs, (_event, ids: unknown) => {
    if (!Array.isArray(ids)) return
    return scheduler.printJobs(ids.filter((id): id is string => typeof id === 'string'))
  })

  ipcMain.handle(IPC.printCancelJob, (_event, id: string) => scheduler.cancel(id))
  ipcMain.handle(IPC.printRetryJob, (_event, id: string) => scheduler.retry(id))
  ipcMain.handle(IPC.printReadPrintable, (_event, id: string) => scheduler.readPrintable(id))
  ipcMain.handle(IPC.printReportPageCount, (_event, id: string, count: number) =>
    scheduler.reportPageCount(id, count),
  )

  ipcMain.handle(IPC.printGetHistory, () => history.list())
  ipcMain.handle(IPC.printClearHistory, async () => {
    await history.clear()
    return history.list()
  })

  ipcMain.handle(IPC.printGetSettings, () => settings.get())
  ipcMain.handle(IPC.printSetSettings, async (_event, patch: Partial<Settings>) => {
    const next = await settings.update(patch)
    scheduler.applySettings(next)
    history.setLimit(next.historyLimit)
    return next
  })
}

const openDialogOptions = {
  title: 'Afegeix documents per imprimir',
  properties: ['openFile', 'multiSelections'] as const,
  filters: [
    { name: 'Documents imprimibles', extensions: ['pdf', 'docx'] },
    { name: 'PDF', extensions: ['pdf'] },
    { name: 'Word', extensions: ['docx'] },
  ],
} satisfies Electron.OpenDialogOptions
