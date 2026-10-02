import { computed, ref } from 'vue'

import { api } from '../api/client'
import type { DocumentRecord, ExtractionStatus, JobRead, UploadResponse } from '../api/types'

// v2: entries no longer carry a document type, so v1 state is not reused.
const STORAGE_KEY = 'cosecre.extractionTracker.v2'
const POLL_INTERVAL_MS = 2000
const STALE_COMPLETED_MS = 1000 * 60 * 60 * 12

export interface TrackedExtractionJob {
  jobId: string
  internalDocNumber: string
  fileName: string
  status: ExtractionStatus
  progress: number
  stageLabel: string
  detail: string
  errorMessage: string | null
  createdAt: string
  updatedAt: string
}

function isClient() {
  return typeof window !== 'undefined'
}

function isTerminalStatus(status: ExtractionStatus) {
  return ['needs_validation', 'validated', 'error'].includes(status)
}

function getStatusMeta(status: ExtractionStatus, errorMessage?: string | null) {
  switch (status) {
    case 'pending':
      return {
        progress: 18,
        stageLabel: 'En cua',
        detail: "Pujat. Esperant torn per llegir-lo.",
      }
    case 'processing':
      return {
        progress: 62,
        stageLabel: 'Llegint',
        detail: 'Els models estan llegint el document i omplint els camps.',
      }
    case 'written_to_sheet':
      return {
        progress: 86,
        stageLabel: 'Desant',
        detail: 'Lectura feta. Desant-ho a Drive i al full de càlcul.',
      }
    case 'needs_validation':
      return {
        progress: 100,
        stageLabel: 'Per revisar',
        detail: 'Fet. Revisa els camps i valida el document.',
      }
    case 'validated':
      return {
        progress: 100,
        stageLabel: 'Validat',
        detail: 'El document ja està confirmat.',
      }
    case 'error':
      return {
        progress: 100,
        stageLabel: 'Error',
        detail: errorMessage || "No s'ha pogut llegir el document.",
      }
  }
}

function loadState(): TrackedExtractionJob[] {
  if (!isClient()) {
    return []
  }

  const raw = window.localStorage.getItem(STORAGE_KEY)
  if (!raw) {
    return []
  }

  try {
    const parsed = JSON.parse(raw) as TrackedExtractionJob[]
    if (!Array.isArray(parsed)) {
      return []
    }
    return parsed
  } catch {
    window.localStorage.removeItem(STORAGE_KEY)
    return []
  }
}

const trackedJobs = ref<TrackedExtractionJob[]>(loadState())
let pollHandle: number | null = null
let polling = false

function persistState() {
  if (!isClient()) {
    return
  }
  window.localStorage.setItem(STORAGE_KEY, JSON.stringify(trackedJobs.value))
}

function sortJobs(jobs: TrackedExtractionJob[]) {
  return [...jobs].sort((left, right) => Date.parse(right.updatedAt) - Date.parse(left.updatedAt))
}

function pruneCompletedJobs() {
  const now = Date.now()
  trackedJobs.value = trackedJobs.value.filter((job) => {
    if (!isTerminalStatus(job.status)) {
      return true
    }
    return now - Date.parse(job.updatedAt) < STALE_COMPLETED_MS
  })
}

function upsertTrackedJob(nextJob: TrackedExtractionJob) {
  const index = trackedJobs.value.findIndex((job) => job.jobId === nextJob.jobId)
  if (index === -1) {
    trackedJobs.value = sortJobs([nextJob, ...trackedJobs.value])
  } else {
    const updated = [...trackedJobs.value]
    updated[index] = nextJob
    trackedJobs.value = sortJobs(updated)
  }
  pruneCompletedJobs()
  persistState()
}

function syncTrackedJob(job: JobRead, fileName?: string) {
  const existing = trackedJobs.value.find((item) => item.jobId === job.id)
  const statusMeta = getStatusMeta(job.status, job.error_message)
  upsertTrackedJob({
    jobId: job.id,
    internalDocNumber: job.internal_doc_number,
    fileName: fileName || existing?.fileName || job.internal_doc_number,
    status: job.status,
    progress: statusMeta.progress,
    stageLabel: statusMeta.stageLabel,
    detail: statusMeta.detail,
    errorMessage: job.error_message,
    createdAt: existing?.createdAt || job.created_at,
    updatedAt: job.updated_at,
  })
}

async function pollActiveJobs() {
  if (polling) {
    return
  }

  const activeJobs = trackedJobs.value.filter((job) => !isTerminalStatus(job.status))
  if (!activeJobs.length) {
    stopPolling()
    return
  }

  polling = true
  try {
    const results = await Promise.allSettled(
      activeJobs.map((job) => api.getJob(job.jobId)),
    )
    results.forEach((result, index) => {
      if (result.status === 'fulfilled') {
        syncTrackedJob(result.value, activeJobs[index]?.fileName)
      }
    })
  } finally {
    polling = false
  }
}

function ensurePolling() {
  if (!isClient() || pollHandle !== null) {
    return
  }
  pollHandle = window.setInterval(() => {
    void pollActiveJobs()
  }, POLL_INTERVAL_MS)
  void pollActiveJobs()
}

function stopPolling() {
  if (!isClient() || pollHandle === null) {
    return
  }
  window.clearInterval(pollHandle)
  pollHandle = null
}

function trackUpload(fileName: string, response: UploadResponse) {
  const statusMeta = getStatusMeta(response.status)
  upsertTrackedJob({
    jobId: response.job_id,
    internalDocNumber: response.internal_doc_number,
    fileName,
    status: response.status,
    progress: statusMeta.progress,
    stageLabel: statusMeta.stageLabel,
    detail: statusMeta.detail,
    errorMessage: null,
    createdAt: new Date().toISOString(),
    updatedAt: new Date().toISOString(),
  })
  ensurePolling()
}

function syncFromDocuments(documents: DocumentRecord[]) {
  documents.forEach((document) => {
    const existing = trackedJobs.value.find(
      (job) => job.internalDocNumber === document.num_doc_intern,
    )
    if (!existing) {
      return
    }
    const statusMeta = getStatusMeta(document.extraction_status, document.error_message)
    upsertTrackedJob({
      ...existing,
      status: document.extraction_status,
      progress: statusMeta.progress,
      stageLabel: statusMeta.stageLabel,
      detail: statusMeta.detail,
      errorMessage: document.error_message,
      updatedAt: document.updated_at || existing.updatedAt,
    })
  })

  if (trackedJobs.value.some((job) => !isTerminalStatus(job.status))) {
    ensurePolling()
    return
  }
  stopPolling()
}

function dismissTrackedJob(jobId: string) {
  trackedJobs.value = trackedJobs.value.filter((job) => job.jobId !== jobId)
  persistState()
  if (!trackedJobs.value.some((job) => !isTerminalStatus(job.status))) {
    stopPolling()
  }
}

export function useExtractionTracker() {
  pruneCompletedJobs()
  persistState()
  if (trackedJobs.value.some((job) => !isTerminalStatus(job.status))) {
    ensurePolling()
  }

  return {
    trackedJobs: computed(() => sortJobs(trackedJobs.value)),
    activeTrackedJobs: computed(() =>
      trackedJobs.value.filter((job) => !isTerminalStatus(job.status)),
    ),
    getTrackedJob(internalDocNumber: string) {
      return trackedJobs.value.find((job) => job.internalDocNumber === internalDocNumber) ?? null
    },
    trackUpload,
    syncFromDocuments,
    dismissTrackedJob,
  }
}
