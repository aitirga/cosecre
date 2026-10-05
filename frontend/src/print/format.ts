import type { JobStatus } from './contract'

export function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} KB`
  return `${(bytes / (1024 * 1024)).toFixed(1).replace('.', ',')} MB`
}

export function formatDuration(ms: number | undefined): string {
  if (ms === undefined || ms < 0) return '—'
  if (ms < 1000) return `${ms} ms`
  if (ms < 60_000) return `${(ms / 1000).toFixed(1).replace('.', ',')} s`
  const minutes = Math.floor(ms / 60_000)
  const seconds = Math.round((ms % 60_000) / 1000)
  return `${minutes} min ${seconds} s`
}

export function formatTime(timestamp: number): string {
  return new Date(timestamp).toLocaleString('ca-ES', {
    day: '2-digit',
    month: 'short',
    hour: '2-digit',
    minute: '2-digit',
  })
}

export const STATUS_LABEL: Record<JobStatus, string> = {
  queued: 'A la cua',
  preparing: 'Convertint',
  ready: 'A punt',
  submitting: 'Enviant',
  spooled: 'A la impressora',
  printing: 'Imprimint',
  completed: 'Imprès',
  failed: 'Error',
  canceled: 'Cancel·lat',
}

/**
 * The shared badge tone per status. Blue for anything on its way to paper,
 * green once it is out, gold while Word is converted, red when it failed.
 * Purple is deliberately absent: in Cosecre it means "the AI did this".
 */
export const STATUS_BADGE: Record<JobStatus, string> = {
  queued: 'badge-neutral',
  preparing: 'badge-gold',
  ready: 'badge-accent',
  submitting: 'badge-accent',
  spooled: 'badge-accent',
  printing: 'badge-accent',
  completed: 'badge-olive',
  failed: 'badge-danger',
  canceled: 'badge-neutral',
}

/** Statuses that should show motion in the UI. */
export function isMoving(status: JobStatus): boolean {
  return (
    status === 'preparing' ||
    status === 'submitting' ||
    status === 'spooled' ||
    status === 'printing'
  )
}
