/**
 * Budget lines (partides) as people read them.
 *
 * esfer@ writes the school year and the level into a line's name
 * ("25-26 Material escolar CI PRIMÀRIA") and the fund into its codi finalista
 * (MOTXILLES2526). Those three are what people look for first, so they are
 * pulled out here into facets the picker can filter, dim and colour by.
 */
import type { Partida } from './api/types'
import { fold } from './composables/useTableQuery'

// ── Funds ───────────────────────────────────────────────────────────────────
// A fund is a colour everywhere it appears: a stripe on a line, a dot in the
// legend. Muted on purpose — graphics only, never text — and never violet,
// which belongs to the AI.

export interface FundTone {
  /** Stripe and dot. */
  solid: string
  /** Tinted fill for a selected or hovered line. */
  soft: string
}

const TONES: Record<string, FundTone> = {
  '': { solid: '#8a9bb5', soft: '#eef2f8' },
  MOTXILLES: { solid: '#1f9aa5', soft: '#e3f4f5' },
  PLADEXOC: { solid: '#e08a2e', soft: '#fcf0e2' },
  FAMILIESMATERIAL: { solid: '#3f6fce', soft: '#e6eefb' },
  FAMILIESSORTIDES: { solid: '#3a9a5c', soft: '#e4f3e9' },
  FAMLLIBRES: { solid: '#c2577a', soft: '#f9e8ee' },
  FAMSOCI: { solid: '#9a6b3c', soft: '#f3ebe2' },
  PMOEPROA: { solid: '#0e7490', soft: '#e0f1f5' },
  ASSIGLLIBRESTEXT: { solid: '#7a8a1f', soft: '#f0f3dc' },
  ROBOTICA: { solid: '#c43a55', soft: '#fbe7eb' },
}

const SPARE: FundTone[] = [
  { solid: '#b07d16', soft: '#f8efd9' },
  { solid: '#4d7c8a', soft: '#e5eff2' },
  { solid: '#a0522d', soft: '#f6e9e2' },
  { solid: '#2e8b7a', soft: '#e1f2ee' },
]

export function fundTone(fons: string): FundTone {
  const known = TONES[fons]
  if (known) return known
  let hash = 0
  for (const ch of fons) hash = (hash * 31 + ch.charCodeAt(0)) >>> 0
  return SPARE[hash % SPARE.length]
}

// ── School year and level ───────────────────────────────────────────────────

const YEAR_PREFIX = /^(\d{2}-\d{2})((?:\s*\/\s*\d{2}-\d{2})*)\s+/

/** `25-26`, from the name's prefix; `''` for a line that is not a year's. */
export function lineYear(nom: string): string {
  return YEAR_PREFIX.exec(nom)?.[1] ?? ''
}

/** Every year a line names — "23-24 / 24-25 Material" is both. */
export function lineYears(nom: string): string[] {
  const match = YEAR_PREFIX.exec(nom)
  if (!match) return []
  return [match[1], ...(match[2].match(/\d{2}-\d{2}/g) ?? [])]
}

/** The name without its year prefix, which the picker shows as a tag. */
export function lineTitle(nom: string): string {
  return nom.replace(YEAR_PREFIX, '').replace(/[\s.]+$/, '')
}

export const LEVELS = ['INF', 'CI', 'CM', 'CS', 'ESO'] as const
export type Level = (typeof LEVELS)[number]

export const LEVEL_LABELS: Record<Level, string> = {
  INF: 'Infantil',
  CI: 'Cicle inicial',
  CM: 'Cicle mitjà',
  CS: 'Cicle superior',
  ESO: 'ESO',
}

/** The levels a line names: "1r PRI CI" is CI, "5è" is CS, "INFANTIL" is INF. */
export function lineLevels(nom: string): Level[] {
  const text = ` ${fold(nom).toUpperCase()} `
  const found = new Set<Level>()
  if (/\bINF(ANTIL)?\b/.test(text)) found.add('INF')
  if (/\bESO\b/.test(text)) found.add('ESO')
  if (/\bCI\b|\b[12](R|N) PRI/.test(text)) found.add('CI')
  if (/\bCM\b|\b(3R|4T) PRI/.test(text)) found.add('CM')
  if (/\bCS\b|\b[56]E\b/.test(text) && !found.has('ESO')) found.add('CS')
  return LEVELS.filter((level) => found.has(level))
}

/** The school year a date falls in: `25-26` from September 2025 to August 2026. */
export function schoolYear(iso: string | null | undefined): string {
  if (!iso) return ''
  const [year, month] = iso.split('-').map(Number)
  if (!year || !month) return ''
  const start = month >= 9 ? year : year - 1
  const two = (n: number) => String(n % 100).padStart(2, '0')
  return `${two(start)}-${two(start + 1)}`
}

// ── Search ──────────────────────────────────────────────────────────────────

/** Folded text a line is searched by: names, codes, fund and what was written about it. */
export function searchText(partida: Partida, parent?: Partida): string {
  return fold(
    [
      partida.nom,
      partida.codi,
      partida.codi_finalista,
      partida.fons_label,
      partida.context,
      parent?.nom ?? '',
    ].join(' '),
  )
}

/** Every word of the query, accents and case aside, somewhere in the line. */
export function matches(haystack: string, query: string): boolean {
  const words = fold(query).split(/\s+/).filter(Boolean)
  return words.every((word) => haystack.includes(word))
}

/** The last segment of a code, which is how people tell sibling lines apart. */
export function shortCode(codi: string): string {
  const dot = codi.lastIndexOf('.')
  return dot >= 0 ? codi.slice(dot) : codi.replace(/^[DI]\//, '').replace(/\/\d+$/, '')
}

export function formatEuros(value: number | null | undefined, digits = 0): string {
  if (value === null || value === undefined) return '—'
  return new Intl.NumberFormat('ca-ES', {
    style: 'currency',
    currency: 'EUR',
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  }).format(value)
}
