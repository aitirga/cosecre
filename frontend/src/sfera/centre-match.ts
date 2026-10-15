import type { SferaCentreOption } from './dashboard'

/**
 * Finds the configured centre among those Esfer@ offers. The setting may be a
 * code («08013305»), a name, or a loose version of either («ramon berenguer»,
 * «Inst. Comas i Sola»). Returns null when nothing is close enough or two
 * centres are equally close, so an ambiguous setting never picks blindly.
 */
const GENERIC = new Set(['escola', 'institut', 'ins', 'inst', 'esc', 'ceip', 'centre', 'col', 'legi', 'collegi', 'de', 'del', 'dels', 'la', 'el', 'els', 'les', 'l', 'd', 'i', 'y'])
const normalize = (v: string) => v.normalize('NFD').replace(/[\u0300-\u036f]/g, '').toLowerCase().replace(/[^a-z0-9]+/g, ' ').trim()
const ROMAN: Record<string, string> = { 1: 'i', 2: 'ii', 3: 'iii', 4: 'iv', 5: 'v', 6: 'vi', 7: 'vii', 8: 'viii', 9: 'ix', 10: 'x' }
const tokens = (v: string) => { const all = normalize(v).split(' ').filter(Boolean).map(t => ROMAN[t] ?? t), kept = all.filter(t => !GENERIC.has(t)); return kept.length ? kept : all }

function distance(a: string, b: string): number {
  let prev = Array.from({ length: b.length + 1 }, (_, i) => i)
  for (let i = 1; i <= a.length; i++) {
    const row = [i]
    for (let j = 1; j <= b.length; j++) row[j] = Math.min(prev[j] + 1, row[j - 1] + 1, prev[j - 1] + (a[i - 1] === b[j - 1] ? 0 : 1))
    prev = row
  }
  return prev[b.length]
}
const close = (a: string, b: string) => a === b
  || (Math.min(a.length, b.length) >= 3 && (a.startsWith(b) || b.startsWith(a)))
  || (Math.min(a.length, b.length) >= 4 && distance(a, b) <= (Math.min(a.length, b.length) >= 7 ? 2 : 1))

function score(wanted: string, name: string): number {
  const a = normalize(wanted), b = normalize(name)
  if (!a || !b) return 0
  if (a === b) return 1
  const wantedTokens = tokens(wanted), nameTokens = tokens(name)
  const found = wantedTokens.filter(t => nameTokens.some(n => close(t, n))).length
  if (!found) return 0
  const recall = found / wantedTokens.length, precision = Math.min(1, found / nameTokens.length)
  return 2 * precision * recall / (precision + recall)
}

export function matchCentre(setting: string, options: SferaCentreOption[]): SferaCentreOption | null {
  const wanted = setting.trim()
  if (!wanted || !options.length) return null
  const code = wanted.match(/\b\d{8}\b/)?.[0]
  const byCode = code && options.find(o => o.code === code)
  if (byCode) return byCode
  // A partial code, e.g. without its leading zero.
  const digits = wanted.replace(/\D/g, '')
  if (digits.length >= 5 && digits.length === wanted.replace(/\s/g, '').length) {
    const partial = options.filter(o => o.code.endsWith(digits) || o.code.includes(digits))
    return partial.length === 1 ? partial[0] : null
  }
  const ranked = options.map(o => ({ o, s: score(wanted, o.name) })).sort((x, y) => y.s - x.s)
  const [best, second] = ranked
  if (best.s < 0.45) return null
  return !second || best.s >= 0.95 && second.s < 0.95 || best.s - second.s >= 0.2 ? best.o : null
}
