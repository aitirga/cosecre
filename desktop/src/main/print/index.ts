/**
 * The print tool's main-process half: printers, LibreOffice conversion, the
 * per-printer queues and the history.
 *
 * Ported from the standalone Cosecre-print app. What stayed behind is what
 * Cosecre already has — its own updater and window — and the log viewer; the
 * diagnostic log is still written, to `<userData>/print/logs/`.
 */
import { join } from 'node:path'
import type { BrowserWindow } from 'electron'

import { IPC } from '../../shared/ipc.js'
import { registerPrintIpc } from './ipc.js'
import { getDriver } from './printing/driver.js'
import { Scheduler } from './queue/scheduler.js'
import { HistoryStore } from './store/history.js'
import { SettingsStore } from './store/settings.js'
import { initLog, log } from './util/log.js'

export interface PrintService {
  /** Removes converted PDFs and LibreOffice profile directories. */
  dispose(): Promise<void>
}

export async function startPrinting(
  userData: string,
  getWindow: () => BrowserWindow | null,
): Promise<PrintService> {
  // Its own folder, so the print settings and history never collide with the
  // desktop shell's store in the same userData directory.
  const dir = join(userData, 'print')
  initLog(join(dir, 'logs'))
  log.info('Print tool starting', { platform: process.platform, electron: process.versions.electron })

  const settings = new SettingsStore(dir)
  const history = new HistoryStore(dir)
  const loaded = await settings.load()
  await history.load(loaded.historyLimit)

  const scheduler = new Scheduler(settings, history, {
    onJobs: (jobs) => getWindow()?.webContents.send(IPC.printJobsChanged, jobs),
    onHistory: (entries) => getWindow()?.webContents.send(IPC.printHistoryChanged, entries),
  })

  registerPrintIpc({ scheduler, settings, history, getWindow })

  // So the log already describes the printers when someone needs to read it.
  // Delayed so it never competes with the window's first paint.
  setTimeout(() => {
    void getDriver()
      .then((driver) => driver.diagnose())
      .catch((error: unknown) => log.error('Diagnostics failed', error))
  }, 3_000)

  return { dispose: () => scheduler.dispose() }
}
