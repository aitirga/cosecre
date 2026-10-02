import type { DocumentFields } from './api/types'

/**
 * The register's columns, as the app shows and edits them.
 *
 * Labels match the spreadsheet headers, so a person moving between the two
 * reads the same words. Closed lists are the exact strings the hub stores.
 */

export const TIPUS_DOCUMENT = [
  'Factura',
  'Factura simplificada',
  'Pressupost',
  'Albarà',
  'Tiquet de rebut',
  'Altres',
] as const
export const ESTATS_PAGAMENT = ['Pagat', 'Pendent de pagament', 'Altres'] as const
export const METODES_PAGAMENT = [
  'Efectiu',
  'Targeta de prepagament',
  'Transferència bancària',
  'Targeta de dèbit',
  'Rebut domiciliat',
  'Altres',
] as const
export const COMPTES = [
  'General',
  'Material i Sortides',
  'Menjador',
  'Caixeta',
  'Targeta Prepagament',
] as const
export const ESTATS_SUBMINISTRAMENT = ['Subministrat', 'No subministrat', 'No aplica'] as const

export type FieldKey = Exclude<keyof DocumentFields, 'validat' | 'origen'>

export interface FieldDef {
  key: FieldKey
  label: string
  kind: 'text' | 'area' | 'date' | 'amount' | 'choice' | 'code'
  options?: readonly string[]
  /** Read by the models, so a value may carry a review flag. */
  ai?: boolean
  /** Spans the full width of its section. */
  wide?: boolean
  placeholder?: string
}

export interface FieldSection {
  id: string
  title: string
  fields: FieldDef[]
}

export const SECTIONS: FieldSection[] = [
  {
    id: 'document',
    title: 'Document',
    fields: [
      { key: 'tipus_document', label: 'Tipus document', kind: 'choice', options: TIPUS_DOCUMENT, ai: true },
      { key: 'num_factura', label: 'Núm. factura', kind: 'code', ai: true },
      { key: 'data_factura', label: 'Data factura', kind: 'date', ai: true },
      { key: 'import', label: 'Import (€)', kind: 'amount', ai: true },
      { key: 'cif_proveit', label: 'CIF proveït', kind: 'code', ai: true },
      { key: 'pressupost_afectat', label: 'Compte', kind: 'choice', options: COMPTES, ai: true },
    ],
  },
  {
    id: 'proveidor',
    title: 'Proveïdor',
    fields: [
      { key: 'proveidor', label: 'Proveïdor/a', kind: 'text', ai: true, wide: true },
      { key: 'cif_proveidor', label: 'CIF proveïdor', kind: 'code', ai: true },
      { key: 'compte_corrent', label: 'Compte corrent', kind: 'code', ai: true, placeholder: 'ES00 0000 0000 0000 0000 0000' },
      { key: 'carrer', label: 'Carrer i núm.', kind: 'text', ai: true, wide: true },
      { key: 'codi_postal', label: 'Codi postal', kind: 'code', ai: true },
      { key: 'ciutat', label: 'Ciutat', kind: 'text', ai: true },
    ],
  },
  {
    id: 'compra',
    title: 'Compra',
    fields: [
      { key: 'descripcio', label: 'Descripció (llegida del document)', kind: 'area', ai: true, wide: true },
      {
        key: 'descripcio_compra',
        label: 'Descripció de la compra/servei',
        kind: 'area',
        wide: true,
        placeholder: 'Per a què és: activitat, departament, grup…',
      },
      { key: 'subministrat', label: 'Subministrat', kind: 'choice', options: ESTATS_SUBMINISTRAMENT },
    ],
  },
  {
    id: 'pagament',
    title: 'Pagament',
    fields: [
      { key: 'pagament', label: 'Pagament', kind: 'choice', options: ESTATS_PAGAMENT, ai: true },
      { key: 'metode_pagament', label: 'Mètode de pagament', kind: 'choice', options: METODES_PAGAMENT, ai: true },
      { key: 'data_pagament', label: 'Data de pagament', kind: 'date', ai: true },
      {
        key: 'pagament_observacions',
        label: 'Pagament: explicació',
        kind: 'text',
        wide: true,
        placeholder: 'Explica la situació del pagament',
      },
    ],
  },
]

// ── Formatting ──────────────────────────────────────────────────────────────

/** `yyyy-mm-dd` → `dd/mm/yyyy`. Everything a person sees uses the latter. */
export function formatDate(iso: string | null | undefined): string {
  if (!iso) return ''
  const [year, month, day] = iso.slice(0, 10).split('-')
  return year && month && day ? `${day}/${month}/${year}` : iso
}

/**
 * `d/m/yyyy` (or `d-m-yy`, `d.m.yyyy`) → `yyyy-mm-dd`. Returns `null` for empty
 * input and `undefined` for something that is not a real date.
 */
export function parseDate(text: string): string | null | undefined {
  const value = text.trim()
  if (!value) return null
  const match = value.match(/^(\d{1,2})[/.-](\d{1,2})[/.-](\d{2}|\d{4})$/)
  if (!match) return undefined
  const day = Number(match[1])
  const month = Number(match[2])
  let year = Number(match[3])
  if (year < 100) year += 2000
  const date = new Date(Date.UTC(year, month - 1, day))
  if (date.getUTCDate() !== day || date.getUTCMonth() !== month - 1) return undefined
  return `${year}-${String(month).padStart(2, '0')}-${String(day).padStart(2, '0')}`
}

const amountFormat = new Intl.NumberFormat('ca-ES', {
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
})

export function formatAmount(value: number | null | undefined): string {
  return value == null ? '—' : `${amountFormat.format(value)} €`
}

/** `1.234,56` or `1234.56` → number; `undefined` when it is not a number. */
export function parseAmount(text: string): number | null | undefined {
  let value = text.replace(/[€\s]/g, '')
  if (!value) return null
  if (value.includes(',') && value.includes('.')) {
    value =
      value.lastIndexOf(',') > value.lastIndexOf('.')
        ? value.replace(/\./g, '').replace(',', '.')
        : value.replace(/,/g, '')
  } else if (value.includes(',')) {
    value = value.replace(',', '.')
  }
  const number = Number(value)
  return Number.isFinite(number) ? number : undefined
}

/** "Jev i OpenAI coincideixen (92 %)" — why a suggestion looks the way it does. */
export function describeHint(hint: { source: string; confidence?: number | null; alternative?: string | null }) {
  const sure = hint.confidence != null ? ` (${Math.round(hint.confidence * 100)} %)` : ''
  switch (hint.source) {
    case 'jev+openai':
      return `Els dos models coincideixen${sure}.`
    case 'jev':
      return hint.alternative
        ? `Proposat per Jev${sure}; l'altre model deia «${hint.alternative}».`
        : `Proposat només per Jev${sure}.`
    case 'openai':
      return hint.alternative
        ? `Llegit del document; Jev proposava «${hint.alternative}»${sure}.`
        : 'Llegit del document. Comprova-ho.'
    case 'migracio':
      return hint.alternative
        ? `Valor antic no reconegut: «${hint.alternative}».`
        : 'Deduït de la pestanya antiga; no hi havia original per llegir.'
    default:
      return ''
  }
}
