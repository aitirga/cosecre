import type { RequestKind, RequestStatus } from './api/types'
import type { IconName } from './components/icons'

export const KIND_LABEL: Record<RequestKind, string> = {
  compra: 'Compra',
  pressupost: 'Pressupost',
  consulta: 'Consulta',
  reemborsament: 'Reemborsament',
}

export const KIND_HINT: Record<RequestKind, string> = {
  compra: 'Material o un servei que cal comprar.',
  pressupost: "Diners per a una activitat o una sortida, abans d'encarregar-la.",
  consulta: 'Una pregunta a secretaria.',
  reemborsament: "Has pagat tu: adjunta'n el tiquet o la factura.",
}

export const KIND_ICON: Record<RequestKind, IconName> = {
  compra: 'invoice',
  pressupost: 'bank',
  consulta: 'message',
  reemborsament: 'ticket',
}

export const KINDS: RequestKind[] = ['compra', 'pressupost', 'reemborsament', 'consulta']

export const STATUS_META: Record<RequestStatus, { label: string; tone: string; verb: string }> = {
  oberta: { label: 'Oberta', tone: 'badge-accent', verb: 'Torna a obrir' },
  en_revisio: { label: 'En revisió', tone: 'badge-gold', verb: 'Passa a revisió' },
  aprovada: { label: 'Aprovada', tone: 'badge-olive', verb: 'Aprova' },
  rebutjada: { label: 'Rebutjada', tone: 'badge-danger', verb: 'Rebutja' },
  resolta: { label: 'Resolta', tone: 'badge-neutral', verb: 'Marca com a resolta' },
  cancellada: { label: 'Cancel·lada', tone: 'badge-neutral', verb: 'Cancel·la la sol·licitud' },
}

/** Still waiting on someone: the office, or the person who asked. */
export const OPEN_STATUSES: RequestStatus[] = ['oberta', 'en_revisio']
