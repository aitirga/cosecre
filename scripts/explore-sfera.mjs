/** Read-only discovery using Cosecre's own WebContentsView, DOM and CDP. */
import { app, BrowserWindow, webContents, session } from 'electron'
import { cp, mkdtemp, mkdir, writeFile, readFile, rm } from 'node:fs/promises'
import { createHash } from 'node:crypto'
import { tmpdir } from 'node:os'
import { join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const PORTAL = 'https://formacio.bfgh.aplicacions.ensenyament.gencat.cat'
const SFERA_PATH = '/bfgh/gestioeconomica/'
const READ_POST_PATHS = new Set(['/bfgh/AppJava/bfgh_gesteco/services/factura/cerca/filtre'])
const GICAR = 'https://autenticaciogicar5.extranet.gencat.cat'
const sleep = ms => new Promise(done => setTimeout(done, ms))
async function until(check, label) {
  const end = Date.now() + 30000
  while (Date.now() < end) { try { const value = await check(); if (value) return value } catch {} await sleep(150) }
  throw new Error('Timeout: ' + label)
}
function safeUrl(value) {
  try { const u = new URL(value); return { origin: u.origin, path: u.pathname, hash: u.hash, queryKeys: [...u.searchParams.keys()] } } catch { return { path: '(invalid)' } }
}
const snapshotCode = `(() => {
  const text = e => (e?.innerText || e?.textContent || '').replace(/\\s+/g, ' ').trim();
  const visible = e => e.getClientRects().length > 0;
  const attrs = e => Object.fromEntries([...e.attributes].filter(a => /^(id|name|type|href|ng-|data-ng-|ui-sref|role)/.test(a.name)).map(a => [a.name, a.value]));
  return {
    url: location.origin + location.pathname + location.hash, title: document.title,
    frameworks: {angular: !!window.angular, angularVersion: window.angular?.version?.full, jquery: !!window.jQuery},
    scripts: [...document.scripts].filter(s=>s.src).map(s=>s.src),
    headings: [...document.querySelectorAll('h1,h2,h3,h4')].filter(visible).map(text),
    tables: [...document.querySelectorAll('table')].filter(visible).slice(0,12).map(t => ({ attrs:attrs(t), rows:[...t.rows].slice(0,25).map(r=>[...r.cells].map(text)) })),
    actions: [...document.querySelectorAll('a,button,[role=button],[role=tab],[data-ng-click],[ng-click],input[type=submit]')].filter(visible).slice(0,150).map(e=>({text:text(e)||e.value||e.title||e.getAttribute('aria-label')||'',attrs:attrs(e)})),
    forms: [...document.querySelectorAll('form')].map(f=>({attrs:attrs(f),fields:[...f.querySelectorAll('input,select,textarea')].filter(e=>e.type!=='password'&&e.type!=='hidden').map(e=>({attrs:attrs(e),label:e.labels?.length?[...e.labels].map(text).join(' '):e.getAttribute('placeholder'),required:e.required,options:e.tagName==='SELECT'?[...e.options].slice(0,50).map(o=>({label:text(o),value:o.value})):undefined}))})),
    angularTemplates: [...document.querySelectorAll('[ng-controller],[data-ng-controller],[ng-view],[data-ng-view],[ui-view]')].map(attrs)
  };
})()`

async function main() {
  // Chromium/safeStorage use the app name at startup for their Keychain key.
  // Match the desktop package when copying its regular profile.
  if (process.env.SFERA_PROFILE) app.setName('cosecre-desktop')
  const root = resolve(fileURLToPath(new URL('..', import.meta.url)))
  const source = process.env.SFERA_PROFILE ?? join(root, 'output/playwright/sfera/private-profile')
  const profile = await mkdtemp(join(tmpdir(), 'cosecre-sfera-research-'))
  await cp(source, profile, { recursive: true })
  // A live source profile may contain Chromium process locks. Remove those
  // only from the disposable copy, never from the user's running profile.
  for (const name of ['SingletonLock','SingletonCookie','SingletonSocket']) await rm(join(profile,name),{force:true})
  app.setPath('userData', profile)
  const output = join(root, 'output/playwright/sfera/research')
  await mkdir(output, { recursive: true, mode: 0o700 })
  const network = [], blocked = []
  const guardedSessions = new Set()
  let presentResult = false
  app.on('browser-window-created', (_event, window) => {
    window.on('show', () => { if (!process.env.SFERA_RESEARCH_VISIBLE && !presentResult) window.hide() })
  })
  app.on('web-contents-created', (_event, wc) => {
    const prefs = wc.getLastWebPreferences()
    if (!prefs.sandbox || prefs.preload) return
    if (!guardedSessions.has(wc.session)) {
      guardedSessions.add(wc.session)
      wc.session.webRequest.onBeforeRequest({urls:[PORTAL+'/*',GICAR+'/*']},(details,respond)=>{
        const u=new URL(details.url),verb=details.method
        const authentication=verb==='POST'&&((u.origin===GICAR&&u.pathname.startsWith('/realms/gicar-ad/login-actions/'))||(u.origin===PORTAL&&u.pathname==='/bfgh/Shibboleth.sso/SAML2/POST'))
        const cancel=!['GET','HEAD','OPTIONS'].includes(verb)&&!authentication&&!(verb==='POST'&&u.origin===PORTAL&&READ_POST_PATHS.has(u.pathname))
        if(cancel) blocked.push({method:verb,...safeUrl(details.url)})
        respond({cancel})
      })
    }
    wc.debugger.attach('1.3')
    const requests = new Map()
    wc.debugger.on('message', async (_event, method, params) => {
      if (method === 'Network.requestWillBeSent' && params.request.url.startsWith(PORTAL + '/bfgh/')) {
        const entry = { method: params.request.method, ...safeUrl(params.request.url), resourceType: params.type, headerNames: Object.keys(params.request.headers).filter(k=>!/^cookie|authorization$/i.test(k)) }
        requests.set(params.requestId, entry); network.push(entry)
      }
      if (method === 'Network.responseReceived') {
        const entry = requests.get(params.requestId)
        if (entry) { entry.status = params.response.status; entry.mimeType = params.response.mimeType }
      }
    })
    void wc.debugger.sendCommand('Network.enable')
  })
  let win, portal
  const save = async (name, value) => writeFile(join(output, name + '.json'), JSON.stringify(value, null, 2) + '\n', { mode: 0o600 })
  try {
    if(process.env.SFERA_RESEARCH_FRESH_LOGIN==='1') {
      await app.whenReady()
      const stored=JSON.parse(await readFile(join(profile,'cosecre-desktop.json'),'utf8'))
      const hub=stored.hubUrl.replace(/\/$/,'').replace(/\/api\/v1$/,'')+'/api/v1'
      const token=stored.tokensByHub[stored.hubUrl]?.['cosecre.accessToken']
      const response=await fetch(hub+'/auth/me',{headers:{Authorization:'Bearer '+token},redirect:'error',signal:AbortSignal.timeout(10000)})
      if(!response.ok) throw Error('Cosecre account could not be verified')
      const user=await response.json()
      const context=createHash('sha256').update(JSON.stringify([hub,user.id,'sfera'])).digest('hex')
      const copiedSession=session.fromPartition('persist:cosecre-browser-'+context)
      await copiedSession.clearStorageData(); await copiedSession.clearCache()
    }
    await import('../desktop/out/main/index.js')
    win = await until(() => BrowserWindow.getAllWindows()[0], 'Cosecre window')
    await until(() => win.webContents.executeJavaScript("!!document.querySelector('.account')"), 'signed-in Cosecre shell')
    await win.webContents.executeJavaScript("location.hash='/eines/sfera'")
    portal = await until(() => webContents.getAllWebContents().find(wc=>!wc.isDestroyed() && wc.getURL().startsWith(PORTAL + SFERA_PATH)), 'Esfer@ contents')
    await until(() => !portal.isLoading(), 'portal loads')
    await until(()=>portal.executeJavaScript("!!document.querySelector('table')"),'authenticated portal application ready')
    await sleep(500)
    const snapshot = await portal.executeJavaScript(snapshotCode)
    await save('01-initial', snapshot)
    console.log(JSON.stringify({ stage:'initial', url:snapshot.url, framework:snapshot.frameworks, tables:snapshot.tables.length, actions:snapshot.actions.length, scripts:snapshot.scripts.length }))
    // Optional planned, bounded steps supplied by the author, never by the remote page.
    if (process.env.SFERA_RESEARCH_STEPS) {
      const { run } = await import(resolve(process.env.SFERA_RESEARCH_STEPS))
      await run({ win, portal, snapshotCode, save, network, blocked, sleep, until, present: () => { presentResult = true; win.show(); win.focus() } })
    }
    await save('network', network)
    await save('blocked-writes', blocked)
    await save('summary', { portal: PORTAL, snapshots: true, osPointerSimulation: false, blockedWrites: blocked.length, networkEntries: network.length })
    console.log(JSON.stringify({ completed:true, queries:network.filter(e=>e.resourceType==='XHR'||e.resourceType==='Fetch').length, blockedWrites:blocked, output }, null, 2))
  } catch (error) {
    if (portal && !portal.isDestroyed()) await save('portal-failure-state',{url:safeUrl(portal.getURL()),body:await portal.executeJavaScript('document.body.innerText.slice(0,8000)').catch(()=>'(unavailable)')})
    await save('network-failure',network)
    await save('blocked-writes-failure',blocked)
    await save('failure', { message: error.message })
    console.error(error.message)
    process.exitCode = 1
  } finally {
    for (const wc of webContents.getAllWebContents()) { if (!wc.isDestroyed() && wc.debugger.isAttached()) wc.debugger.detach() }
    for (const window of BrowserWindow.getAllWindows()) window.destroy()
    // Only the newly copied discovery profile is disposable.
    await rm(profile, { recursive: true, force: true })
    app.exit(process.exitCode || 0)
  }
}
void main().catch(error => { console.error(error.message); app.exit(1) })
