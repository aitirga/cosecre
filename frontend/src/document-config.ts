import type { DocumentType } from './api/types'

/**
 * Per-type copy for the shared inbox and detail views.
 *
 * Invoices and tickets are the same pipeline with different wording, so the
 * views are one component and the words live here.
 */
export interface DocumentCopy {
  listTitle: string
  listHeading: string
  singular: string
  plural: string
  routeName: 'invoices' | 'tickets'
  detailRouteName: 'invoice' | 'ticket'
  uploadHeading: string
  uploadLead: string
  queueLead: string
  emptyLead: string
}

export const DOCUMENT_CONFIG: Record<DocumentType, DocumentCopy> = {
  invoice: {
    listTitle: 'Invoices',
    listHeading: 'Synced with the shared Google Sheet',
    singular: 'invoice',
    plural: 'invoices',
    routeName: 'invoices',
    detailRouteName: 'invoice',
    uploadHeading: 'Add invoices',
    uploadLead:
      'PDFs and images are processed in parallel. Each file becomes one invoice and reaches the sheet as soon as extraction succeeds.',
    queueLead: 'Uploads appear here with live progress, and survive a page reload.',
    emptyLead: 'No invoices yet. Upload one to seed the sheet.',
  },
  ticket: {
    listTitle: 'Tickets',
    listHeading: 'Synced with the shared Google Sheet',
    singular: 'ticket',
    plural: 'tickets',
    routeName: 'tickets',
    detailRouteName: 'ticket',
    uploadHeading: 'Add tickets',
    uploadLead:
      'PDFs and images are processed in parallel. Each file becomes one ticket and reaches the sheet as soon as extraction succeeds.',
    queueLead: 'Uploads appear here with live progress, and survive a page reload.',
    emptyLead: 'No tickets yet. Upload one to seed the sheet.',
  },
}
