/**
 * Interactive read-only probe of Esfer@ with Cosecre's own Electron and a copy
 * of the user's profile. Every non-read request to the portal is cancelled
 * (SFERA_PROBE_ALLOW_VALIDATE=1 lets only /factura/validate through;
 * SFERA_PROBE_ALLOW_INVOICE_WRITES=1 also /factura/desa, for an end-to-end export);
 * a localhost control port (token protected) runs bounded GETs and snapshots.
 *
 *   SFERA_PROFILE=~/Library/Application\ Support/cosecre-desktop \
 *     node_modules/.bin/electron scripts/probe-sfera.mjs
 */
import { app, BrowserWindow, webContents } from 'electron'
import { cp, mkdtemp, mkdir, readFile, rm, writeFile } from 'node:fs/promises'
import { createServer } from 'node:http'
import { createHash, randomBytes } from 'node:crypto'
import { tmpdir } from 'node:os'
import { join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const PORTAL = 'https://formacio.bfgh.aplicacions.ensenyament.gencat.cat'
const GICAR = 'https://autenticaciogicar5.extranet.gencat.cat'
const BASE = '/bfgh/AppJava/bfgh_gesteco/services'
const READ_POSTS = new Set([BASE + '/factura/cerca/filtre', BASE + '/ingres/cerca/filtre', BASE + '/proveidor/cerca/filtre', BASE + '/reservaDespesa/cerca/filtre/', BASE + '/compteExtrapressupostari/cerca/filtre', ...['consultaLlibreDespeses','consultaLlibreIngres','llibre/comptesCorrents','llibre/caixa','saldos/comptes','consultaPrevisionesTesoreria','consultaCodiFinalista','movimentsProveidor','movimentsAportadorGeneric'].map(p => BASE + '/consulta/' + p)])
const sleep = ms => new Promise(done => setTimeout(done, ms))
async function until(check, label, ms = 60000) {
  const end = Date.now() + ms
  while (Date.now() < end) { try { const v = await check(); if (v) return v } catch {} await sleep(250) }
  throw new Error('Timeout: ' + label)
}
const HEADER_KEYS = ['TOKEN','USR_CENTRE','USR_ROL','USR_USERNAME_AWA','USR_NOM_AWA','USR_COGNOM1_AWA','USR_COGNOM2_AWA','FUNCIONALITAT-ORIGEN','PESTANYA-ORIGEN','Cache-Control','Pragma','If-Modified-Since']
const ACCESS = `(() => { const s = window.angular?.element(document.body).injector()?.get('$http')?.defaults.headers.common; const c = window.AppClient?.CENTRE_SESSIO; if (!s || !s.TOKEN) return null; return { centre: c ? JSON.parse(JSON.stringify(c)) : null, headers: Object.fromEntries(${JSON.stringify(HEADER_KEYS)}.filter(k => s[k] != null).map(k => [k, String(typeof s[k] === "function" ? s[k]() : s[k])])) } })()`

async function main() {
  // safeStorage keys the Keychain item by app name; match the packaged app's.
  app.setName('cosecre-desktop')
  const root = resolve(fileURLToPath(new URL('..', import.meta.url)))
  const source = process.env.SFERA_PROFILE
  if (!source) throw new Error('SFERA_PROFILE is required')
  const profile = await mkdtemp(join(tmpdir(), 'cosecre-sfera-probe-'))
  await cp(source, profile, { recursive: true, filter: p => !/(Cache|GPUCache|Code Cache|DawnGraphiteCache|DawnWebGPUCache|blob_storage)$/.test(p) })
  for (const n of ['SingletonLock','SingletonCookie','SingletonSocket','DevToolsActivePort']) await rm(join(profile, n), { force: true })
  app.setPath('userData', profile)
  // End-to-end runs against a local Hub, in the temporary copy only: point it at
  // SFERA_PROBE_HUB_URL with a token for account SFERA_PROBE_HUB_USER, and file the
  // existing (still encrypted) GICAR credential under that Hub's context.
  if (process.env.SFERA_PROBE_HUB_URL) {
    const hubUrl = process.env.SFERA_PROBE_HUB_URL, store = join(profile, 'cosecre-desktop.json')
    const current = JSON.parse(await readFile(store, 'utf8'))
    await writeFile(store, JSON.stringify({ ...current, hubUrl, tokensByHub: { ...current.tokensByHub, [hubUrl]: { 'cosecre.accessToken': process.env.SFERA_PROBE_HUB_TOKEN, 'cosecre.refreshToken': process.env.SFERA_PROBE_HUB_REFRESH ?? '' } } }), { mode: 0o600 })
    const credentials = join(profile, 'sfera-credentials.json')
    const records = JSON.parse(await readFile(credentials, 'utf8').catch(() => '{}'))
    const [existing] = Object.values(records)
    const root = hubUrl.replace(/\/$/, '').replace(/\/api\/v1$/, '') + '/api/v1'
    const context = createHash('sha256').update(JSON.stringify([root, Number(process.env.SFERA_PROBE_HUB_USER), 'sfera'])).digest('hex')
    if (existing) await writeFile(credentials, JSON.stringify({ ...records, [context]: existing }), { mode: 0o600 })
  }
  const out = join(root, 'output/playwright/sfera/probe')
  await mkdir(out, { recursive: true, mode: 0o700 })
  const blocked = [], xhr = []
  const guarded = new Set()
  app.on('web-contents-created', (_e, wc) => {
    const prefs = wc.getLastWebPreferences()
    if (!prefs.sandbox || prefs.preload || guarded.has(wc.session)) return
    guarded.add(wc.session)
    wc.session.webRequest.onBeforeRequest({ urls: [PORTAL + '/*', GICAR + '/*'] }, (d, respond) => {
      const u = new URL(d.url), m = d.method
      const auth = m === 'POST' && ((u.origin === GICAR && u.pathname.startsWith('/realms/gicar-ad/login-actions/')) || (u.origin === PORTAL && u.pathname.startsWith('/bfgh/Shibboleth.sso/')))
      // SFERA_PROBE_ALLOW_VALIDATE=1 lets invoice validation through (diagnosis); saving stays blocked.
      const validate = process.env.SFERA_PROBE_ALLOW_VALIDATE === '1' && ['PUT','POST'].includes(m) && u.origin === PORTAL && u.pathname === BASE + '/factura/validate'
        // SFERA_PROBE_ALLOW_INVOICE_WRITES=1: an end-to-end invoice export (validate + desa) in formació.
        || process.env.SFERA_PROBE_ALLOW_INVOICE_WRITES === '1' && m === 'PUT' && u.origin === PORTAL && [BASE + '/factura/validate', BASE + '/factura/desa'].includes(u.pathname)
      const cancel = !['GET','HEAD','OPTIONS'].includes(m) && !auth && !validate && !(m === 'POST' && READ_POSTS.has(u.pathname))
      if (cancel) blocked.push({ method: m, path: u.pathname })
      if (u.pathname.startsWith(BASE)) xhr.push({ id: d.id, method: m, path: u.pathname, cancel, ...(m !== 'GET' ? { bodyBytes: d.uploadData?.reduce((n, p) => n + (p.bytes?.length ?? 0), 0) } : {}) })
      respond({ cancel })
    })
    // Writes: record the headers actually sent (token redacted) and the status, to compare portal and Cosecre requests.
    wc.session.webRequest.onSendHeaders({ urls: [PORTAL + BASE + '/*'] }, d => {
      const x = d.method !== 'GET' && xhr.findLast(r => r.id === d.id)
      if (x) x.headers = Object.fromEntries(Object.entries(d.requestHeaders).map(([k, v]) => [k, /token|cookie/i.test(k) ? `[${String(v).length}]` : v]))
    })
    wc.session.webRequest.onCompleted({ urls: [PORTAL + BASE + '/*'] }, d => {
      const x = d.method !== 'GET' && xhr.findLast(r => r.id === d.id)
      if (x) x.status = d.statusCode
    })
  })
  await import('../desktop/out/main/index.js')
  const win = await until(() => BrowserWindow.getAllWindows()[0], 'Cosecre window')
  // Other agents drive the desktop with the pointer; this probe window must not take their clicks.
  win.setIgnoreMouseEvents(true); win.setFocusable(false); win.setSize(1440, 900)
  await until(() => win.webContents.executeJavaScript("!!document.querySelector('.account')"), 'signed-in Cosecre shell')
  await win.webContents.executeJavaScript(`location.hash=${JSON.stringify(process.env.SFERA_PROBE_ROUTE ?? '/eines/sfera')}`)
  const find = () => webContents.getAllWebContents().find(wc => !wc.isDestroyed() && wc !== win.webContents && /^https:/.test(wc.getURL()))
  const portalOf = () => { const p = find(); if (!p) throw new Error('no portal view'); return p }

  const token = randomBytes(16).toString('hex')
  const access = () => portalOf().executeJavaScript(ACCESS)
  const server = createServer(async (req, res) => {
    const send = (code, v) => { res.writeHead(code, { 'content-type': 'application/json' }); res.end(JSON.stringify(v, null, 1)) }
    try {
      if (req.headers['x-probe'] !== token) return send(403, { error: 'token' })
      let body = ''; for await (const c of req) body += c
      const q = body ? JSON.parse(body) : {}
      if (q.action === 'state') { const p = find(); return send(200, { views: webContents.getAllWebContents().map(w => { try { const u = new URL(w.getURL()); return u.origin + u.pathname + u.hash } catch { return w.getURL().slice(0, 40) } }), title: p?.getTitle(), access: p ? await access().catch(e => String(e)).then(a => a && a.headers ? { centre: a.centre, headerKeys: Object.keys(a.headers) } : a) : null, blocked, xhr: xhr.slice(-40) }) }
      if (q.action === 'eval') return send(200, { value: await portalOf().executeJavaScript(q.code) })
      if (q.action === 'shell') return send(200, { value: await win.webContents.executeJavaScript(q.code) })
      if (q.action === 'shot') { const img = await (q.shell ? win.webContents : win.webContents).capturePage(); await writeFile(join(out, (q.name || 'shot') + '.png'), img.toPNG(), { mode: 0o600 }); return send(200, { saved: q.name }) }
      if (q.action === 'fetch') {
        const a = await access(); if (!a) return send(409, { error: 'no access' })
        const method = q.body ? 'POST' : 'GET'
        if (method === 'POST' && !READ_POSTS.has(BASE + q.path)) return send(400, { error: 'post not allowed' })
        const started = performance.now()
        const r = await portalOf().session.fetch(PORTAL + BASE + q.path, { method, headers: { ...a.headers, ...(q.body ? { 'Content-Type': 'application/json' } : {}) }, ...(q.body ? { body: JSON.stringify(q.body) } : {}), credentials: 'include', redirect: 'manual', signal: AbortSignal.timeout(30000) })
        const text = await r.text()
        let data; try { data = JSON.parse(text) } catch { data = text.slice(0, 2000) }
        if (q.save) await writeFile(join(out, q.save + '.json'), JSON.stringify(data, null, 1), { mode: 0o600 })
        return send(200, { status: r.status, type: r.headers.get('content-type'), ms: Math.round(performance.now() - started), size: text.length, data: q.full ? data : Array.isArray(data) ? { length: data.length, first: data.slice(0, q.n ?? 2) } : data })
      }
      send(400, { error: 'action' })
    } catch (e) { send(500, { error: String(e?.message || e) }) }
  })
  server.listen(0, '127.0.0.1', async () => {
    const { port } = server.address()
    await writeFile(join(out, 'control.json'), JSON.stringify({ port, token }), { mode: 0o600 })
    console.log('control ready on', port)
  })
  app.on('before-quit', () => { void rm(profile, { recursive: true, force: true }) })
}
void main().catch(e => { console.error(e.message); app.exit(1) })
