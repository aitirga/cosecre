/**
 * Numbers and colours for what the Assistent shows.
 *
 * The series order was validated (dataviz `validate_palette.js`, light, on
 * white): every adjacent pair clears ΔE 8.4 under colour-blindness simulation
 * and 16.8 for normal vision. Slot 1 is the brand blue. Violet stays out —
 * it means "the AI did this" — and so do the status hues' own steps. Aqua,
 * yellow and pink sit under 3:1 on white, which is why every chart has a
 * tooltip and a table view.
 */
export const SERIES_COLORS = [
  '#3f6fce', // brand blue (accent-600)
  '#eb6834', // orange
  '#1baf7a', // aqua
  '#eda100', // yellow
  '#e87ba4', // pink
  '#008300', // green
  '#b5179e', // plum
  '#e34948', // red
]

const plain = new Intl.NumberFormat('ca-ES', { maximumFractionDigits: 2 })
const money = new Intl.NumberFormat('ca-ES', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
const compactFormat = new Intl.NumberFormat('ca-ES', { notation: 'compact', maximumFractionDigits: 1 })

function isMoney(unit: string) {
  return unit.trim() === '€' || unit.trim().toLowerCase() === 'eur'
}

export function formatNumber(value: number | null | undefined, unit = '', compact = false): string {
  if (value == null || !Number.isFinite(value)) return '—'
  const text = compact && Math.abs(value) >= 10000
    ? compactFormat.format(value)
    : isMoney(unit) && !compact
      ? money.format(value)
      : plain.format(value)
  return unit ? `${text} ${unit.trim() === 'eur' ? '€' : unit.trim()}` : text
}

/** Headings that say a column holds euros. */
const MONEY_COLUMN = /import|total|€|euros?|gast|pagat|saldo|suma|amount|preu|cost/i
const DATE_VALUE = /^\d{4}-\d{2}-\d{2}(T[\d:.]+)?$/

/** A table cell, formatted by what it holds and what its column is called. */
export function formatCell(value: unknown, column: string): string {
  if (value == null || value === '') return ''
  if (typeof value === 'boolean') return value ? 'Sí' : 'No'
  if (typeof value === 'number') {
    return MONEY_COLUMN.test(column) ? `${money.format(value)} €` : plain.format(value)
  }
  if (typeof value === 'string' && DATE_VALUE.test(value)) {
    const [date, time] = value.split('T')
    const [y, m, d] = (date ?? '').split('-')
    return `${d}/${m}/${y}${time ? ` ${time.slice(0, 5)}` : ''}`
  }
  return String(value)
}

export function isNumeric(value: unknown) {
  return typeof value === 'number'
}
