/**
 * The print tool's state, shared by every component of the tool.
 *
 * Module-scoped reactive state, like `composables/useAuth.ts`: the queue lives
 * in the desktop main process and outlives the page, so leaving the tool and
 * coming back must find the same jobs — and must not subscribe twice.
 */
import { computed, reactive, readonly } from 'vue'

import { usePlatform } from '../platform'
import {
  isTerminal,
  type AddFilesResult,
  type ConverterStatus,
  type HistoryEntry,
  type Job,
  type PrintBridge,
  type PrinterInfo,
  type PrintOptions,
  type Settings,
} from './contract'

export interface PrintNotice {
  id: number
  tone: 'error' | 'info'
  text: string
}

interface PrintState {
  ready: boolean
  jobs: Job[]
  history: HistoryEntry[]
  printers: PrinterInfo[]
  settings: Settings | null
  converter: ConverterStatus | null
  selectedJobId: string | null
  notices: PrintNotice[]
}

const state = reactive<PrintState>({
  ready: false,
  jobs: [],
  history: [],
  printers: [],
  settings: null,
  converter: null,
  selectedJobId: null,
  notices: [],
})

let started: Promise<void> | null = null
let noticeId = 0

/** Statuses during which a job sits with the spooler and its options are fixed. */
export function isSending(job: Job): boolean {
  return job.status === 'submitting' || job.status === 'spooled' || job.status === 'printing'
}

/** Options stop being editable the moment a job is handed to the spooler. */
export function isLocked(job: Job): boolean {
  return isTerminal(job.status) || isSending(job)
}

function start(bridge: PrintBridge): Promise<void> {
  started ??= (async () => {
    const [printers, settings, history, jobs, converter] = await Promise.all([
      bridge.listPrinters().catch(() => [] as PrinterInfo[]),
      bridge.getSettings(),
      bridge.getHistory(),
      bridge.getJobs(),
      bridge.getConverterStatus(),
    ])
    Object.assign(state, { printers, settings, history, jobs, converter, ready: true })
    if (!state.selectedJobId) state.selectedJobId = jobs[0]?.id ?? null

    bridge.onJobUpdate((next) => {
      state.jobs = next
      // Keep a sensible selection: the first job once there is one, and a
      // neighbour when the selected job is removed.
      if (!state.selectedJobId || !next.some((job) => job.id === state.selectedJobId)) {
        state.selectedJobId = next[0]?.id ?? null
      }
    })
    bridge.onHistoryUpdate((next) => (state.history = next))
  })().catch((error: unknown) => {
    started = null
    throw error
  })
  return started
}

export function usePrint() {
  const bridge = usePlatform().print

  function notify(tone: PrintNotice['tone'], text: string) {
    const notice: PrintNotice = { id: ++noticeId, tone, text }
    state.notices.push(notice)
    setTimeout(() => dismiss(notice.id), tone === 'error' ? 8000 : 3500)
  }

  function dismiss(id: number) {
    state.notices = state.notices.filter((notice) => notice.id !== id)
  }

  /** Select the first new job and surface a notice for anything rejected. */
  function absorb(result: AddFilesResult) {
    if (result.jobs.length > 0 && !state.selectedJobId) {
      state.selectedJobId = result.jobs[0]!.id
    }
    for (const item of result.rejected) {
      const name = item.path.split(/[/\\]/).pop() ?? item.path
      notify('error', `${name}: ${item.reason}`)
    }
  }

  /** Every call goes through here, so a failing IPC call surfaces instead of vanishing. */
  async function guarded<T>(action: (bridge: PrintBridge) => Promise<T>): Promise<T | undefined> {
    if (!bridge) return undefined
    try {
      return await action(bridge)
    } catch (error) {
      notify('error', error instanceof Error ? error.message : String(error))
      return undefined
    }
  }

  async function addPaths(paths: string[]) {
    if (paths.length === 0) return
    const result = await guarded((b) => b.addFiles(paths))
    if (result) absorb(result)
  }

  const selectedJob = computed(() => state.jobs.find((job) => job.id === state.selectedJobId))

  /** Jobs that "Print all" would send: everything not yet handed to a printer. */
  const pending = computed(() =>
    state.jobs.filter(
      (job) => job.status === 'ready' || job.status === 'queued' || job.status === 'preparing',
    ),
  )
  const sendingCount = computed(() => state.jobs.filter(isSending).length)
  const finishedCount = computed(() => state.jobs.filter((job) => isTerminal(job.status)).length)

  /** A Word file is waiting and there is nothing to convert it with. */
  const needsConverter = computed(
    () =>
      Boolean(state.converter && !state.converter.available) &&
      state.jobs.some((job) => job.extension === '.docx'),
  )

  return {
    available: Boolean(bridge),
    state: readonly(state),
    selectedJob,
    pending,
    sendingCount,
    finishedCount,
    needsConverter,

    init: () => (bridge ? start(bridge) : Promise.resolve()),
    select: (jobId: string | null) => (state.selectedJobId = jobId),
    notify,
    dismiss,

    readPrintable: (jobId: string) => bridge!.readPrintable(jobId),
    reportPageCount: (jobId: string, count: number) =>
      guarded((b) => b.reportPageCount(jobId, count)),

    addPaths,
    addDropped: (files: FileList | File[]) => {
      if (!bridge) return Promise.resolve()
      // `File.path` is gone since Electron 32; the preload resolves it instead.
      return addPaths([...files].map((file) => bridge.getPathForFile(file)).filter(Boolean))
    },
    pickFiles: async () => {
      const result = await guarded((b) => b.pickFiles())
      if (result) absorb(result)
    },
    refreshPrinters: async () => {
      const printers = await guarded((b) => b.refreshPrinters())
      if (printers) state.printers = printers
    },

    updateOptions: (jobId: string, patch: Partial<PrintOptions>) =>
      guarded((b) => b.updateJobOptions(jobId, patch)),
    applyToAll: async (patch: Partial<PrintOptions>) => {
      if (await guarded((b) => b.applyOptionsToAll(patch))) {
        notify('info', 'Aplicat a tots els documents pendents.')
      }
    },
    printJobs: (jobIds: string[]) =>
      jobIds.length ? guarded((b) => b.printJobs(jobIds)) : Promise.resolve(),
    cancelJob: (jobId: string) => guarded((b) => b.cancelJob(jobId)),
    retryJob: (jobId: string) => guarded((b) => b.retryJob(jobId)),
    removeJob: (jobId: string) => guarded((b) => b.removeJob(jobId)),
    clearFinished: () => guarded((b) => b.clearFinished()),

    clearHistory: async () => {
      await guarded((b) => b.clearHistory())
      state.history = []
    },
    saveSettings: async (patch: Partial<Settings>) => {
      const settings = await guarded((b) => b.setSettings(patch))
      if (!settings) return
      // The LibreOffice path may have changed, so re-check the converter.
      state.settings = settings
      state.converter = (await guarded((b) => b.getConverterStatus())) ?? state.converter
    },
  }
}
