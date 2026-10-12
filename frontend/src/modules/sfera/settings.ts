import { request } from '../../api/client'

export interface SferaSettings { access_url: string; centre: string }
const path = '/apps/cosecre-sfera/settings'
export async function getSettings(): Promise<SferaSettings> {
  const result = await request<{ settings: Partial<SferaSettings> }>(path)
  return { access_url: result.settings.access_url ?? '', centre: result.settings.centre ?? '' }
}
export function saveSettings(settings: SferaSettings) {
  return request(path, { method: 'PUT', body: JSON.stringify(settings) })
}
