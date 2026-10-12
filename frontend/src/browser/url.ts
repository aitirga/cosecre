/** Secure portals plus loopback HTTP for reproducible local browser checks. */
export function portalUrl(value: unknown): string {
  if (typeof value !== 'string' || value.length > 2048) throw new Error('La URL no és vàlida.')
  let url: URL
  try { url = new URL(value.trim()) } catch { throw new Error('Introdueix una URL completa (https://…).') }
  if (url.username || url.password || [...url.searchParams.keys()].some((key) => /password|token|secret|authorization|^code$/i.test(key))) {
    throw new Error('La URL no pot contenir credencials ni tokens.')
  }
  if (url.protocol !== 'https:' && !(url.protocol === 'http:' && ['localhost', '127.0.0.1', '[::1]'].includes(url.hostname))) {
    throw new Error('Cal una URL HTTPS. HTTP només està permès per a proves locals.')
  }
  return url.href
}
