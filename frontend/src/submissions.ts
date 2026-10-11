import type { ExtractionStatus } from './api/types'

/**
 * A teacher's reading of where their document is. The office's labels ("Per
 * revisar") describe the office's work; these describe the teacher's own.
 */
export const SUBMISSION_STATUS: Record<ExtractionStatus, { label: string; tone: string }> = {
  pending: { label: 'Llegint', tone: 'badge-neutral' },
  processing: { label: 'Llegint', tone: 'badge-accent' },
  written_to_sheet: { label: 'Llegint', tone: 'badge-accent' },
  needs_validation: { label: 'Per validar', tone: 'badge-gold' },
  validated: { label: 'Validada', tone: 'badge-olive' },
  error: { label: "No s'ha pogut llegir", tone: 'badge-danger' },
}
