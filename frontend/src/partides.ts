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

// ── Splitting an amount between lines ───────────────────────────────────────

export interface Share {
  id: number
  amount: number | null
}

const cents = (value: number) => Math.round(value * 100) / 100

/**
 * Give `total` out in the proportions `weights` already have (evenly when they
 * are all zero), to the cent, with the rounding left on the biggest share.
 */
function spread(ids: number[], weights: number[], total: number): Record<number, number> {
  const out: Record<number, number> = {}
  if (!ids.length) return out
  const sum = weights.reduce((acc, w) => acc + Math.max(0, w), 0)
  let given = 0
  ids.forEach((id, index) => {
    const share = sum > 0 ? (Math.max(0, weights[index]) / sum) * total : total / ids.length
    out[id] = Math.floor(share * 100) / 100
    given += out[id]
  })
  const biggest = ids.reduce((a, b) => (out[b] > out[a] ? b : a))
  out[biggest] = cents(out[biggest] + total - given)
  return out
}

/** Shares split evenly. One line alone takes it all, and says so with `null`. */
export function evenShares(ids: number[], total: number | null): Share[] {
  if (ids.length < 2 || !total) return ids.map((id) => ({ id, amount: ids.length < 2 ? null : 0 }))
  const amounts = spread(ids, ids.map(() => 1), total)
  return ids.map((id) => ({ id, amount: amounts[id] }))
}

/**
 * One line set to `value`; the others make room, or take what is left, in the
 * proportions they had — so the split keeps adding up to `total` whatever is
 * typed. Without a total there is nothing to keep, and only that line changes.
 */
export function rebalance(shares: Share[], id: number, value: number, total: number | null): Share[] {
  if (total === null || total <= 0 || shares.length < 2) {
    return shares.map((share) => (share.id === id ? { ...share, amount: cents(Math.max(0, value)) } : share))
  }
  const fixed = cents(Math.min(Math.max(0, value), total))
  const others = shares.filter((share) => share.id !== id)
  const rest = spread(
    others.map((share) => share.id),
    others.map((share) => share.amount ?? 0),
    cents(total - fixed),
  )
  return shares.map((share) => ({ ...share, amount: share.id === id ? fixed : rest[share.id] }))
}

/** A line joins with an even share; the others shrink in proportion to make room. */
export function addShare(shares: Share[], id: number, total: number | null): Share[] {
  if (!shares.length) return [{ id, amount: null }]
  if (shares.length === 1 || !total) return evenShares([...shares.map((s) => s.id), id], total)
  const next = [...shares, { id, amount: 0 }]
  return rebalance(next, id, total / next.length, total)
}

/** A line leaves; what it had goes back to the others, in proportion. */
export function removeShare(shares: Share[], id: number, total: number | null): Share[] {
  const left = shares.filter((share) => share.id !== id)
  if (left.length < 2) return left.map((share) => ({ ...share, amount: null }))
  if (!total) return left
  const amounts = spread(
    left.map((share) => share.id),
    left.map((share) => share.amount ?? 0),
    total,
  )
  return left.map((share) => ({ ...share, amount: amounts[share.id] }))
}
