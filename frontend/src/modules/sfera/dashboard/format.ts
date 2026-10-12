/** Number and date formatting for the Esfer@ dashboard, in Catalan. */
const eur = new Intl.NumberFormat('ca-ES', { style: 'currency', currency: 'EUR' })
const eur0 = new Intl.NumberFormat('ca-ES', { style: 'currency', currency: 'EUR', maximumFractionDigits: 0 })
const compact = new Intl.NumberFormat('ca-ES', { notation: 'compact', maximumFractionDigits: 1 })

export const euro = (v: number) => eur.format(v)
/** Whole euros, for headline figures where cents are noise. */
export const euro0 = (v: number) => eur0.format(v)
/** Axis ticks: 120 k €, 1,2 M €. */
export const euroTick = (v: number) => (v === 0 ? '0' : `${compact.format(v)} €`)
export const pct = (part: number, whole: number) => (whole > 0 ? part / whole : 0)
export const pctLabel = (ratio: number) => `${Math.round(ratio * 100).toLocaleString('ca-ES')} %`

const longDay = new Intl.DateTimeFormat('ca-ES', { day: 'numeric', month: 'short', year: 'numeric', timeZone: 'UTC' })
const shortDay = new Intl.DateTimeFormat('ca-ES', { day: 'numeric', month: 'short', timeZone: 'UTC' })
const monthName = new Intl.DateTimeFormat('ca-ES', { month: 'long', year: 'numeric', timeZone: 'UTC' })
const monthShort = new Intl.DateTimeFormat('ca-ES', { month: 'short', timeZone: 'UTC' })
const asDate = (iso: string) => new Date(iso.length === 7 ? `${iso}-01T00:00:00Z` : `${iso}T00:00:00Z`)

export const dayLabel = (iso: string | null) => (iso ? longDay.format(asDate(iso)) : '—')
export const dayShort = (iso: string) => shortDay.format(asDate(iso))
export const monthLabel = (ym: string) => monthName.format(asDate(ym))
export const monthTick = (ym: string) => monthShort.format(asDate(ym)).replace('.', '')
export const clock = (iso: string) => new Date(iso).toLocaleTimeString('ca-ES', { hour: '2-digit', minute: '2-digit' })
export const seconds = (ms: number) => (ms < 1000 ? `${ms} ms` : `${(ms / 1000).toLocaleString('ca-ES', { maximumFractionDigits: 1 })} s`)

/** Round tick values covering [min, max]: 0, 50 000, 100 000… */
export function niceTicks(min: number, max: number, count = 4): number[] {
  if (max === min) max = min + 1
  const raw = (max - min) / count
  const mag = 10 ** Math.floor(Math.log10(raw))
  const step = [1, 2, 2.5, 5, 10].map(m => m * mag).find(s => s >= raw) ?? 10 * mag
  const ticks: number[] = []
  for (let v = Math.floor(min / step) * step; v <= max + step * 0.001; v += step) ticks.push(Math.round(v * 100) / 100)
  if (ticks[ticks.length - 1] < max) ticks.push(ticks[ticks.length - 1] + step)
  return ticks
}

export const normalize = (s: string) => s.normalize('NFD').replace(/[̀-ͯ]/g, '').toLowerCase()
