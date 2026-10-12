import type { WebContents } from 'electron'
import type { InvoiceWriteTrace } from '../../../../frontend/src/sfera/invoice-bridge'
export const TRAINING_ORIGIN = 'https://formacio.bfgh.aplicacions.ensenyament.gencat.cat'
export const SERVICES = '/bfgh/AppJava/bfgh_gesteco/services'
const KEYS = ['TOKEN','USR_CENTRE','USR_ROL','USR_USERNAME_AWA','USR_NOM_AWA','USR_COGNOM1_AWA','USR_COGNOM2_AWA','FUNCIONALITAT-ORIGEN','PESTANYA-ORIGEN','Cache-Control','Pragma','If-Modified-Since']
const MAX_RESPONSE = 12 * 1024 * 1024
export class PortalError extends Error {}
/** A short, user-facing reason from an Esfer@ response body, with session values redacted. */
function describe(body: string, headers: Record<string,string>): string {
  let detail = body
  try {
    const json = JSON.parse(body) as unknown
    const fields = json && typeof json === 'object' ? ['message','missatge','error','detail','descripcio'].map(k => (json as Record<string,unknown>)[k]) : []
    detail = typeof json === 'string' ? json : (fields.find(v => typeof v === 'string' && v.trim()) as string | undefined) ?? JSON.stringify(json)
  } catch { detail = body.replace(/<(script|style)[\s\S]*?<\/\1>/gi,' ').replace(/<[^>]*>/g,' ') }
  for (const value of Object.values(headers)) if (value.length > 2) detail = detail.split(value).join('[dada privada]')
  return detail.replace(/\s+/g,' ').trim().slice(0,500)
}
export interface PortalAccess { centre: string; headers: Record<string,string> }
export interface PortalConnection {
  access: PortalAccess
  assertContext(): Promise<void>
  request(method: 'GET' | 'POST' | 'PUT', path: string, body?: unknown): Promise<unknown>
}
export async function connectPortal(wc: WebContents, url: string, valid: () => boolean, traces: InvoiceWriteTrace[] = []): Promise<PortalConnection> {
  const read = async (): Promise<PortalAccess> => {
    if (!valid() || wc.isDestroyed()) throw new PortalError('El context de Cosecre ha canviat.')
    const configured = new URL(url), current = new URL(wc.getURL())
    if (configured.origin !== TRAINING_ORIGIN || configured.pathname !== '/bfgh/gestioeconomica/' || current.origin !== TRAINING_ORIGIN || current.pathname !== configured.pathname) throw new PortalError('Aquesta prova només escriu al portal de formació. Obre el navegador i identifica’t.')
    const result = await wc.executeJavaScript(`(() => {
      const h=window.angular?.element(document.body).injector()?.get('$http')?.defaults.headers.common;
      const c=window.AppClient?.CENTRE_SESSIO?.codiExtern;
      if(!h || !h.TOKEN || !c) return null;
      return {centre:String(c),headers:Object.fromEntries(${JSON.stringify(KEYS)}.filter(k=>h[k]!=null).map(k=>[k,String(typeof h[k]==='function'?h[k]():h[k])]))};
    })()`) as PortalAccess | null
    if (!result || !/^\d{8}$/.test(result.centre) || !result.headers.TOKEN || !result.headers.USR_CENTRE) throw new PortalError('Identifica’t i selecciona el centre a Esfer@ abans de preparar la factura.')
    return result
  }
  const access = await read()
  const assertContext = async () => {
    const now = await read()
    if (now.centre !== access.centre || ['TOKEN','USR_CENTRE','USR_ROL','USR_USERNAME_AWA'].some(k => now.headers[k] !== access.headers[k])) throw new PortalError('La sessió o el centre ha canviat. Torna a preparar la factura.')
  }
  return {
    access, assertContext,
    async request(method,path,body) {
      if (!path.startsWith('/') || path.includes('://') || path.includes('..')) throw new PortalError('Ruta no permesa.')
      if (method === 'PUT' && !['/factura/validate','/factura/desa'].includes(path)) throw new PortalError('Operació d’escriptura no permesa.')
      if (method === 'POST' && path !== '/factura/cerca/filtre') throw new PortalError('Operació no permesa.')
      await assertContext()
      const start=performance.now(), trace: InvoiceWriteTrace={method,path:SERVICES+path,status:null,durationMs:0}
      traces.push(trace)
      try {
        // Writes run as a same-origin fetch inside the portal page, so they keep
        // its cookies, origin and referrer. The portal's $http is not used: its
        // interceptors swallow error responses (status and body), which hid
        // Esfer@'s actual reason behind a status-less rejection.
        if (method === 'PUT') {
          const response = await wc.executeJavaScript(`(async () => {
            const abort = new AbortController(), timer = setTimeout(() => abort.abort(), 20000);
            try {
              const r = await fetch(${JSON.stringify(SERVICES + path)}, {method:'PUT',credentials:'same-origin',redirect:'manual',signal:abort.signal,
                headers:{...${JSON.stringify(access.headers)},Accept:'application/json, text/plain, */*','Content-Type':'application/json;charset=utf-8'},
                body:${JSON.stringify(JSON.stringify(body))}});
              if (r.type === 'opaqueredirect') return {status:0,error:'redirect'};
              const text = await r.text(), meta = ['allow','content-type','x-powered-by'].map(k => r.headers.get(k) && k + ': ' + r.headers.get(k)).filter(Boolean).join('; ');
              return text.length > ${MAX_RESPONSE} ? {status:r.status,error:'too-large'} : {status:r.status,text,meta};
            } catch (e) { return {status:0,error:e && e.name === 'AbortError' ? 'timeout' : String(e && e.message || e)}; }
            finally { clearTimeout(timer); }
          })()`) as {status:number;text?:string;error?:string;meta?:string}
          trace.status=response.status > 0 ? response.status : null
          await assertContext()
          if (response.error==='too-large') throw new PortalError('La resposta d’Esfer@ és massa gran.')
          if (response.status < 200 || response.status >= 300 || response.error) {
            // Response metadata (Allow, content type, server stack) tells which layer refused the request.
            // A PUT that fails server-side is forwarded to the container's error page, which
            // rejects PUT: the 405 hides a data error (e.g. a line without cost centre).
            if (response.status===405 && /PUT is not supported/i.test(response.text ?? '')) {
              trace.error='HTTP 405 (error intern d’Esfer@ amb les dades)'
              throw new PortalError(`Esfer@ no ha pogut processar ${path}: ha fallat amb les dades enviades (405 genèric). Sol indicar que falta un camp obligatori, com el centre de cost de la línia.`)
            }
            const detail=[describe(response.text ?? response.error ?? '',access.headers),response.status > 0 && response.meta ? `[${response.meta.slice(0,200)}]` : ''].filter(Boolean).join(' ')
            trace.error=response.status > 0 ? `HTTP ${response.status}${detail?`: ${detail}`:''}` : response.error==='redirect' ? 'Redirecció (sessió caducada?)' : response.error==='timeout' ? 'Temps d’espera esgotat (20 s)' : `Error de xarxa: ${detail}`
            throw new PortalError(response.status > 0 ? `Esfer@ ha rebutjat ${path} (HTTP ${response.status})${detail?`: ${detail}`:'.'}` : `${trace.error} a ${path}. No es confirma cap desament.`)
          }
          const text=response.text ?? ''
          if (!text.trim()) return null
          try { return JSON.parse(text) as unknown }
          catch { throw new PortalError(`Esfer@ ha respost ${path} amb un format inesperat (${describe(text,access.headers) || 'buit'}). Revisa la sessió.`) }
        }
        const response=await wc.session.fetch(TRAINING_ORIGIN+SERVICES+path,{method,headers:{...access.headers,Accept:'application/json',...(body!==undefined?{'Content-Type':'application/json'}:{})},...(body!==undefined?{body:JSON.stringify(body)}:{}),credentials:'include',redirect:'manual',signal:AbortSignal.timeout(20000)})
        trace.status=response.status
        if (!response.ok || !response.headers.get('content-type')?.includes('application/json')) throw new PortalError(`Esfer@ ha rebutjat la petició (${response.status}). Revisa la sessió i els permisos.`)
        const text=await response.text()
        if (Buffer.byteLength(text)>12*1024*1024) throw new PortalError('La resposta d’Esfer@ és massa gran.')
        return text ? JSON.parse(text) as unknown : null
      } finally { trace.durationMs=Math.round(performance.now()-start) }
    },
  }
}
