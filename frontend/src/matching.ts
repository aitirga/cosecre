/**
 * The one confidence number, and the colour it is read in.
 *
 * Mirrors ``services/matching/confidence.py``: the bands are the same there,
 * so a test on the server and a dot on the screen never disagree.
 */
import type { Band, Categoria, MatchStatus } from './api/types'

export const HIGH = 85
export const MEDIUM = 60

export function band(confidence: number | null | undefined): Band {
  if (confidence == null) return 'none'
  if (confidence >= HIGH) return 'high'
  if (confidence >= MEDIUM) return 'medium'
  return 'low'
}

export const BAND_LABEL: Record<Band, string> = {
  high: 'Molt probable',
  medium: 'Probable, revisa',
  low: 'Dubtosa',
  none: 'Sense proposta',
}

export const STATUS_LABEL: Record<MatchStatus, string> = {
  unmatched: 'Sense proposta',
  proposed: 'Proposta',
  no_match: 'Sense factura',
  confirmed: 'Confirmat',
  rejected: 'Cap factura',
  not_applicable: 'No aplica',
}

export const CATEGORIA_LABEL: Record<Categoria, string> = {
  pagament: 'Pagament',
  comissio: 'Comissió bancària',
  traspas_intern: 'Traspàs intern',
  ingres: 'Ingrés',
  devolucio: 'Devolució',
  saldo_inicial: 'Saldo inicial',
}

export const SOURCE_LABEL: Record<string, string> = {
  caixa_xls: 'Excel La Caixa',
  prepaid_pdf: 'PDF targeta',
  caixeta_sheet: 'Full de la caixeta',
}

export const SIGNAL_LABEL: Record<string, string> = {
  amount: 'Import',
  number: 'Núm. factura',
  cif: 'CIF',
  iban: 'IBAN',
  name: 'Proveïdor',
  date: 'Data',
  consistency: 'Compte i mètode',
}

/** Deciders that are a model rather than a rule or a person. */
const AI_DECIDERS = new Set(['openai', 'jev', 'jev+openai'])

/** Whether a match was proposed by the AI — shown in the AI's violet. */
export function byAi(decidedBy: string | null | undefined): boolean {
  return AI_DECIDERS.has(decidedBy ?? '')
}

export const DECIDED_LABEL: Record<string, string> = {
  rules: 'Regles',
  openai: 'gpt-6-luna',
  jev: 'Jev',
  'jev+openai': 'gpt-6-luna + Jev',
  person: 'A mà',
}
