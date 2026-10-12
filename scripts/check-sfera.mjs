/** Run with the installed Electron: local fake hub/portal, isolated userData. */
import { app, BrowserWindow, webContents, dialog } from 'electron'
import assert from 'node:assert/strict'
import { createServer } from 'node:http'
import { mkdtemp, mkdir, writeFile, readFile, rm } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { resolve, join } from 'node:path'
import { fileURLToPath } from 'node:url'

async function main() {
const root = resolve(fileURLToPath(new URL('..', import.meta.url)))
const data = await mkdtemp(join(tmpdir(), 'cosecre-sfera-check-'))
app.setPath('userData', data)
const output = join(root, 'output/playwright/sfera')
await mkdir(output, { recursive: true })
let centre = 'Centre de prova'
let configured = true
let savingFails = false
// Export plans the mocked Hub hands to the desktop runner, and what the runner reported back.
const exportHub = { plans: new Map(), results: [], resultFails: false, preflights: [], reconciles: [] }
let url
const requests = []
const user = (id = 1, role = 'admin') => ({ id, email: `user${id}@example.invalid`, display_name: 'Compte de prova', role, is_admin: role === 'admin', is_active: true, status: 'active', created_at: '2026-10-12T12:00:00Z' })
const hub = createServer(async (req, res) => {
  requests.push({ path: req.url, authorization: req.headers.authorization ?? null })
  if (req.url.startsWith('/portal')) {
    res.setHeader('Content-Type', 'text/html; charset=utf-8')
    if (req.url === '/portal/download') { res.setHeader('Content-Disposition', 'attachment; filename="prova.txt"'); res.end('prova'); return }
    if (req.url === '/portal/redirect') { res.writeHead(302, { Location: '/portal/next' }); res.end(); return }
    res.end(`<!doctype html><title>Portal de prova Esfer@</title><style>body{font:18px system-ui;background:#fbf6ec;padding:36px;color:#294761}button,a{padding:10px;display:inline-block;margin:8px}</style><h1>Esfer@ · portal local de prova</h1><p id="location">${req.url}</p><p>Inicia sessió manualment. Aquest portal només comprova la integració.</p><button onclick="document.cookie='portal_session=manual;path=/'">Iniciar sessió de prova</button><a href="/portal/next">Següent</a><a href="/portal/redirect">Redirecció</a><button onclick="window.open('/portal/login','login')">Autenticació en finestra</button><button onclick="window.open('about:blank','blank')">Finestra buida</button><a href="/portal/download">Descarregar</a><a href="file:///etc/passwd">URL bloquejada</a>`)
    return
  }
  if (!req.url.startsWith('/api/')) {
    const path = new URL(req.url, origin).pathname
    const name = path.startsWith('/assets/') || /^\/(registerSW\.js|sw\.js|workbox-[a-zA-Z0-9]+\.js|manifest\.webmanifest|favicon\.svg)$/.test(path) ? path.slice(1) : 'index.html'
    const file = resolve(root, 'frontend/dist', name)
    if (!file.startsWith(resolve(root, 'frontend/dist') + '/')) { res.statusCode = 404; res.end(); return }
    try {
      const contents = await readFile(file)
      res.setHeader('Content-Type', name.endsWith('.js') ? 'application/javascript' : name.endsWith('.css') ? 'text/css' : name.endsWith('.svg') ? 'image/svg+xml' : name.endsWith('.webmanifest') ? 'application/manifest+json' : 'text/html')
      res.end(contents)
    } catch { res.statusCode = 404; res.end() }
    return
  }
  res.setHeader('Content-Type', 'application/json')
  let result = []
  if (req.url.endsWith('/meta')) result = { product: 'cosecre-hub', name: 'Hub de prova', version: 'test', api_version: '1', api_prefix: '/api/v1', apps: ['cosecre-docs'], has_users: true, capabilities: { auth: true, app_settings: true, documents: true, llm: false }, accepts_registration: false }
  else if (req.url.endsWith('/auth/me')) { const token = req.headers.authorization ?? ''; result = user(token.includes('user2') ? 2 : 1, token.includes('professor') ? 'professor' : token.includes('staff') ? 'administratiu' : 'admin') }
  else if (req.url.endsWith('/apps/cosecre-sfera/settings')) {
    if (req.method === 'PUT') {
      if (savingFails) { res.statusCode = 503; res.end(JSON.stringify({ detail: 'Error simulat de desament' })); return }
      let body = ''; for await (const part of req) body += part
      const value = JSON.parse(body); centre = value.centre; url = value.access_url; configured = Boolean(url)
    }
    result = { app_slug: 'cosecre-sfera', settings: { access_url: configured ? url : '', centre } }
  } else if (req.url.endsWith('/documents/settings')) result = { registry_sheet_name: 'Registre', sheet_name: 'Factures', ticket_sheet_name: 'Tiquets', openai_model: 'test', polling_interval_seconds: 30 }
  else if (req.url.endsWith('/users')) result = [user()]
  else if (req.url.includes('/notifications/count')) result = { count: 0 }
  else if (req.url.includes('/changes')) result = { undo: null, redo: null }
  const sferaPath = req.url.replace(/^.*\/api\/v1/, '')
  const planOut = (id, plan) => ({ id, state: plan.state ?? 'approved', plan_hash: 'f'.repeat(64), context: plan.context, created_at: '2026-10-12T10:00:00Z', approved_at: '2026-10-12T10:00:00Z',
    items: [{ id: 1, source_ref: 'DOC-' + id.slice(-2), document_id: null, movement_id: null, duplicate_key: '1:X', state: plan.state ?? 'approved', problems: [], payload: plan.payload,
      invoice: { document_number: plan.payload.identificadorDocProveidor, accounting_date: '2026-10-12', total: '1.00' }, remote_id: null, remote_code: null, attempts: [] }] })
  if (sferaPath === '/sfera/capabilities') result = [{ entity: 'supplier_invoice', action: 'create', environment: 'training', status: 'verified', verified_on: '2026-10-12', scope: 'Prova' }]
  else if (sferaPath === '/sfera/preflight' && req.method === 'POST') { let body = ''; for await (const part of req) body += part; exportHub.preflights.push(JSON.parse(body)); result = [{ source_ref: 'DIAGNOSTIC', duplicate_key: '1:X', state: 'ready', problems: [], payload: {} }] }
  else if (sferaPath === '/sfera/export-plans' && req.method === 'GET') result = [...exportHub.plans].map(([id, plan]) => ({ id, state: plan.state ?? 'approved', environment: 'training', centre_code: plan.context.centre_code, items: 1, created_at: '2026-10-12T10:00:00Z' }))
  else if (/^\/sfera\/export-plans\/[^/]+$/.test(sferaPath) && req.method === 'GET') {
    const id = sferaPath.split('/').pop(), plan = exportHub.plans.get(id)
    if (!plan) { res.statusCode = 404; res.end(JSON.stringify({ detail: 'Pla no trobat.' })); return }
    result = planOut(id, plan)
  }
  const reconcileMatch = sferaPath.match(/^\/sfera\/export-plans\/([^/]+)\/items\/\d+\/reconcile$/)
  if (reconcileMatch && req.method === 'POST') { let body = ''; for await (const part of req) body += part; exportHub.reconciles.push(JSON.parse(body)); result = planOut(reconcileMatch[1], exportHub.plans.get(reconcileMatch[1])) }
  const exportMatch = req.url.match(/\/sfera\/export-plans\/([^/]+)\/items\/(\d+)\/(claim|result)$/)
  if (exportMatch && req.method === 'POST') {
    const plan = exportHub.plans.get(exportMatch[1])
    if (!plan) { res.statusCode = 404; res.end(JSON.stringify({ detail: 'Pla no trobat.' })); return }
    if (exportMatch[3] === 'claim') { plan.attempt += 1; result = { plan_id: exportMatch[1], item_id: Number(exportMatch[2]), attempt_id: plan.attempt, payload: plan.payload, duplicate_key: '1:X', context: plan.context } }
    else {
      if (exportHub.resultFails) { res.statusCode = 503; res.end(JSON.stringify({ detail: 'Hub no disponible' })); return }
      let body = ''; for await (const part of req) body += part
      exportHub.results.push(JSON.parse(body)); result = {}
    }
  }
  res.end(JSON.stringify(result))
})
await new Promise((done) => hub.listen(0, '127.0.0.1', done))
const origin = `http://127.0.0.1:${hub.address().port}`
url = origin + '/portal'
const hubUrl = origin + '/api/v1'
await writeFile(join(data, 'cosecre-desktop.json'), JSON.stringify({ hubUrl, tokensByHub: { [hubUrl]: { 'cosecre.accessToken': 'local-admin-user1', 'cosecre.refreshToken': 'local-refresh' } } }))

const sleep = (ms) => new Promise((done) => setTimeout(done, ms))
async function until(check, label) {
  const deadline = Date.now() + 15000
  while (Date.now() < deadline) { try { const value = await check(); if (value) return value } catch {} await sleep(100) }
  throw new Error(`Timeout: ${label}`)
}
let win
let secondHub
let webWindow
let portal
let checks = []
const record = (text) => { checks.push(text); console.log('✓', text) }
const evalApp = (code) => win.webContents.executeJavaScript(`(() => { ${code.startsWith('const ') || code.startsWith('window.cosecreDesktop.removeToken') ? code : 'return (' + code + ')'} })()`)
const click = (label) => evalApp(`(() => { const el = [...document.querySelectorAll('button,a')].find(e => e.textContent.trim() === ${JSON.stringify(label)}); if (!el) throw Error('Missing button'); el.click(); })()`)
async function openPortal() {
  await until(() => evalApp("!!document.querySelector('.account')"), 'authenticated shell ready')
  await evalApp("location.hash = '/eines/sfera'")
  portal = await until(() => webContents.getAllWebContents().find((wc) => !wc.isDestroyed() && wc.getURL().startsWith(origin + '/portal')), 'portal opens')
  await until(async () => !portal.isLoading() && (await evalApp("document.querySelector('.browser-surface')?.getBoundingClientRect().height > 100")), 'portal loaded and measured')
  await sleep(200)
}
async function context(token, newHub = null) {
  await evalApp(`window.cosecreDesktop.removeToken('cosecre.accessToken'); window.cosecreDesktop.setToken('cosecre.accessToken', ${JSON.stringify(token)}); window.cosecreDesktop.setToken('cosecre.refreshToken','local-refresh')`)
  if (newHub) await evalApp(`window.cosecreDesktop.setHubUrl(${JSON.stringify(newHub)})`)
  else win.webContents.reload()
  await until(() => !win.webContents.isLoading(), 'context reload')
  await until(() => evalApp("!!document.querySelector('.account')"), 'authenticated reload ready')
}

async function switchHub(nextHub) {
  let loaded = new Promise(done => win.webContents.once('did-finish-load', done))
  await evalApp(`void window.cosecreDesktop.setHubUrl(${JSON.stringify(nextHub)})`)
  await loaded
  await evalApp("(() => { window.cosecreDesktop.setToken('cosecre.accessToken','local-admin-user1'); window.cosecreDesktop.setToken('cosecre.refreshToken','local-refresh') })()")
  loaded = new Promise(done => win.webContents.once('did-finish-load', done))
  win.webContents.reload()
  await loaded
  await until(() => evalApp("!!document.querySelector('.account')"), 'new hub account ready')
}
try {
  await import('../desktop/out/main/index.js')
  win = await until(() => BrowserWindow.getAllWindows().find(w => !w.isDestroyed()), 'Cosecre window')
  if(process.env.COSECRE_CHECK_BACKGROUND) {win.setIgnoreMouseEvents(true);win.setFocusable(false);win.hide()} else {win.show();win.focus()}
  await until(() => !win.webContents.isLoading(), 'renderer load')
  await openPortal()
  assert.equal(await portal.executeJavaScript("typeof require + ':' + typeof process + ':' + typeof window.cosecreDesktop"), 'undefined:undefined:undefined')
  assert.equal(portal.getLastWebPreferences().sandbox, true)
  assert.equal(portal.getLastWebPreferences().contextIsolation, true)
  assert.equal(portal.getLastWebPreferences().nodeIntegration, false)
  record('Remote portal: sandbox, no Node, no Cosecre bridge')
  assert.equal(await evalApp("!![...document.querySelectorAll('button')].find(e => e.textContent.trim() === 'Esfer@')"), true)
  assert.equal(await evalApp("!!document.querySelector('a[href=\"#/settings?tab=sfera\"]')"), true)
  record('Sidebar: Eines → Esfer@ subtree, Navegador and Configuració deep link')
  await portal.executeJavaScript("document.cookie='portal_session=manual;path=/'", true)
  const partition1 = portal.session
  assert.equal((await portal.session.cookies.get({ name: 'portal_session' }))[0].value, 'manual')
  await portal.executeJavaScript("document.querySelector('a[href=\"/portal/next\"]').click()", true)
  await until(() => portal.getURL().endsWith('/next'), 'next navigation')
  await until(() => evalApp("![...document.querySelectorAll('button')].find(e => e.textContent.trim() === 'Enrere')?.disabled"), 'back enabled')
  await click('Enrere'); await until(() => portal.getURL() === url, 'back')
  await click('Endavant'); await until(() => portal.getURL().endsWith('/next'), 'forward')
  await click('Inici'); await until(() => portal.getURL() === url, 'home')
  await click('Recarregar'); await until(() => !portal.isLoading(), 'reload')
  await portal.executeJavaScript("location.href='/portal/redirect'")
  await until(() => portal.getURL().endsWith('/next'), 'authentication-style redirect')
  record('Back, forward, reload, home and HTTP redirects')
  await portal.executeJavaScript("void window.open('/portal/login','login')")
  const popup = await until(() => BrowserWindow.getAllWindows().find(w => w !== win), 'login popup')
  await until(() => !popup.webContents.isLoading(), 'popup load')
  assert.equal(await popup.webContents.executeJavaScript("typeof require + ':' + typeof window.cosecreDesktop"), 'undefined:undefined')
  assert.equal(popup.webContents.session, portal.session)
  popup.close()
  record('Login popup: isolated, same portal session')
  const originalDialog = dialog.showMessageBox
  try {
    dialog.showMessageBox = async () => ({ response: 0, checkboxChecked: false })
    await click('Esborrar sessió')
    await until(() => evalApp("![...document.querySelectorAll('button')].find(e => e.textContent.trim() === 'Esborrar sessió')?.disabled"), 'clear-session cancel')
    assert.equal((await portal.session.cookies.get({ name: 'portal_session' })).length, 1)
    dialog.showMessageBox = async () => ({ response: 1, checkboxChecked: false })
    await click('Esborrar sessió')
    await until(async () => (await portal.session.cookies.get({ name: 'portal_session' })).length === 0 && !portal.isLoading() && portal.getURL() === url, 'clear-session confirm')
    await portal.executeJavaScript("document.cookie='portal_session=manual;path=/'", true)
    record('Clear session: cancel preserves cookies, confirm removes them')
  } finally { dialog.showMessageBox = originalDialog }
  const downloadPath = join(data, 'prova.txt')
  portal.session.once('will-download', (_event, item) => item.setSavePath(downloadPath))
  await portal.executeJavaScript("document.querySelector('a[href=\"/portal/download\"]').click()", true)
  await until(async () => (await readFile(downloadPath, 'utf8')) === 'prova', 'download completion')
  record('Portal downloads: user-chosen file without execution')
  const id = await evalApp("new Promise(resolve => { const off=window.cosecreDesktop.browser.onState(s => { off(); resolve(s.id) }); document.querySelectorAll('button').forEach(e => { if(e.textContent.trim()==='Recarregar') e.click() }) })")
  assert.equal(await evalApp(`window.cosecreDesktop.browser.command(${JSON.stringify(id)}, 'execute-script').then(()=>false,()=>true)`), true)
  assert.equal(await evalApp(`window.cosecreDesktop.browser.layout(${JSON.stringify(id)}, {x:0,y:0,width:Infinity,height:10}).then(()=>false,()=>true)`), true)
  record('Bridge: unknown commands and non-finite geometry refused')
  const child = () => win.contentView.children.filter(v => 'webContents' in v && v.webContents === portal).length
  assert.equal(child(), 1)
  await evalApp("const d=document.createElement('div'); d.id='test-dialog'; d.setAttribute('role','dialog'); d.textContent='Diàleg de prova'; document.body.append(d)")
  await until(() => child() === 0, 'hide beneath dialog')
  await evalApp("document.getElementById('test-dialog').remove()")
  await until(() => child() === 1, 'restore after dialog')
  if(!process.env.COSECRE_CHECK_BACKGROUND) {win.show();win.focus()} win.setSize(1050, 740)
  app.focus({ steal: true })
  await until(() => evalApp('!document.hidden'), 'resized window foreground')
  await sleep(350)
  const resizedView = await until(() => win.contentView.children.find(v => 'webContents' in v && v.webContents === portal), 'resized view visible')
  const bounds = resizedView.getBounds()
  assert(bounds.width > 200 && bounds.x > 150 && bounds.x + bounds.width <= win.getContentSize()[0])
  await evalApp("window.scrollTo(0,200)")
  await until(() => child() === 1, 'scrolled view visible')
  record('Native view: sidebar preserved, resize, scrolling, dialog hide/restore')
  await click('Configuració')
  await until(() => portal.isDestroyed(), 'route exit closes contents')
  await until(() => evalApp("document.querySelector('input[type=url]')?.value.includes('/portal')"), 'settings deep link')
  await evalApp("const i=document.querySelector('input[type=url]'); i.value='file:///tmp/portal'; i.dispatchEvent(new Event('input',{bubbles:true}))")
  await click('Desar')
  await until(() => evalApp("document.querySelector('[role=alert]')?.textContent.includes('HTTPS')"), 'URL validation')
  savingFails = true
  await evalApp(`const i=document.querySelector('input[type=url]'); i.value=${JSON.stringify(url)}; i.dispatchEvent(new Event('input',{bubbles:true})); const c=[...document.querySelectorAll('input')].find(e=>e!==i); c.value='Centre editat'; c.dispatchEvent(new Event('input',{bubbles:true}))`)
  await click('Desar'); await until(() => evalApp("document.body.textContent.includes('Error simulat')"), 'save failure feedback')
  savingFails = false
  await click('Desar'); await until(() => evalApp("document.body.textContent.includes('Configuració desada.')"), 'save success')
  assert.equal(centre, 'Centre editat')
  await writeFile(join(output, 'settings.png'), await (await win.capturePage()).toPNG())
  record('Settings: validation, failure feedback, editable save and persistence')
  await until(() => evalApp("!!document.querySelector('input[type=password]')"), 'personal credential fields')
  const fixturePassword = 'synthetic-password-for-local-test'
  await evalApp(`const u=document.querySelector('input[autocomplete=username]'); u.value='gicar-test-user'; u.dispatchEvent(new Event('input',{bubbles:true})); const p=document.querySelector('input[type=password]'); p.value=${JSON.stringify(fixturePassword)}; p.dispatchEvent(new Event('input',{bubbles:true})); const c=document.querySelector('.credentials input[type=checkbox]'); c.click()`)
  await click('Desar el meu accés')
  await until(() => evalApp("document.body.textContent.includes('Accés personal desat')"), 'credential save')
  const credentialStatus = await evalApp("window.cosecreDesktop.browser.credentialsStatus('sfera')")
  assert.equal(credentialStatus.username, 'gicar-test-user')
  assert.equal(credentialStatus.configured, true)
  assert.equal(credentialStatus.automatic, true)
  assert.equal(Object.hasOwn(credentialStatus, 'password'), false)
  const disk = await readFile(join(data, 'sfera-credentials.json'), 'utf8')
  assert.equal(disk.includes(fixturePassword), false)
  assert.equal(await evalApp("document.querySelector('input[type=password]').value"), '')
  record('Personal credentials: encrypted on disk, password cleared, status never returns password')
  await openPortal()
  assert.equal((await portal.session.cookies.get({ name: 'portal_session' })).length, 1)
  record('Cookies survive leaving the browser route')
  // Read-only data adapter against an intercepted training origin. The fixture
  // uses synthetic access headers and never reaches the external service.
  const trainingOrigin = 'https://formacio.bfgh.aplicacions.ensenyament.gencat.cat'
  const localPortalUrl = url
  let trainingExpired = false, trainingBadShape = false, trainingRedirect = false, trainingCentreChange = false
  let outsideTrainingRequests = 0
  let invoiceValidationFails = false
  let invoiceValidationRejected = false
  let desaFails = false
  const savedPortalInvoices=[]
  const dataRequests = []
  await partition1.protocol.handle('https', async request => {
    const u = new URL(request.url)
    if (u.origin !== trainingOrigin) outsideTrainingRequests++
    assert.equal(u.origin, trainingOrigin)
    if (u.pathname === '/bfgh/gestioeconomica/') return new Response(`<title>Esfer@ de prova</title><h1>Centre de prova</h1><script>window.AppClient={CENTRE_SESSIO:{codiExtern:'08000001'}};const http=async c=>{const r=await fetch(c.url,{method:c.method,headers:{...c.headers,'Content-Type':'application/json;charset=utf-8'},body:JSON.stringify(c.data)});if(!r.ok)throw {status:r.status};return {status:r.status,data:await r.json()}};http.defaults={headers:{common:{TOKEN:'synthetic-sfera-token',USR_CENTRE:8000001,USR_ROL:45,'FUNCIONALITAT-ORIGEN':45}}};window.angular={element:()=>({injector:()=>({get:()=>http})})};</script>`, { headers: { 'Content-Type': 'text/html' } })
    dataRequests.push({ path:u.pathname, method:request.method })
    assert.equal(request.headers.get('authorization'),null)
    assert.equal(request.headers.get('TOKEN'),'synthetic-sfera-token')
    assert.equal(request.headers.get('USR_CENTRE'),'8000001')
    assert.equal(request.headers.get('FUNCIONALITAT-ORIGEN'),'45')
    assert.equal(request.headers.get('USR_ROL'),'45')
    if (trainingRedirect) return new Response(null,{status:302,headers:{Location:'https://example.invalid/login'}})
    if (trainingCentreChange) await portal.executeJavaScript("window.AppClient.CENTRE_SESSIO.codiExtern='08000002'")
    if (trainingExpired) return new Response('<h1>Identifica’t</h1>', { headers: { 'Content-Type': 'text/html' } })
    const service='/bfgh/AppJava/bfgh_gesteco/services'
    let payload
    if(u.pathname===service+'/pressupost/centre') { assert.equal(request.method,'GET'); payload=[{id:123,idCentre:555,any:2026,tipusPressupost:'G',estat:'A',totalPressupostatIngres:2000,totalPressupostatDespesa:2000}] }
    else if(u.pathname===service+'/proveidor/cerca') { assert.equal(request.method,'GET'); payload=[{id:1,nom:'Proveïdor de prova',nifProveidor:'A00000000',nomMunicipi:'Barcelona',estat:'A',saldoProveidor:0,token:'must-not-cross-bridge'}] }
    else if(u.pathname===service+'/factura/cerca/filtre') {
      assert.equal(request.method,'POST')
      const filter=await request.json()
      assert.equal(filter.idPressupost,123);assert.equal(filter.dataRegistreDesde,'2026/01/01');assert.equal(filter.despesaSimplificada,'F')
      payload=filter.numFactura?savedPortalInvoices.filter(i=>i.identificadorDocProveidor===filter.numFactura):[{id:77,codiGeneratSistema:'FC202600000001',identificadorDocProveidor:'PROVA-001',proveidor:{nom:'Proveïdor de prova'},importTotalFinal:121,importPendent:121,anulat:'F',liquidat:'F',dataRegistre:1767225600000},...savedPortalInvoices]
    } else if(u.pathname===service+'/partidaPressupost/cerca/filtre/123/DESPESA') payload=[{id:61,codiPartida:'D/226003900/4210',nomPartida:'Comissions bancàries',centreCostDesglosPartida:[{id:71,nom:'General'}]}]
    else if(u.pathname===service+'/compteBancari/comptesActiuVigent') payload=[{id:51,idCentre:555,nomDescriptiuCompte:'Compte general de prova'}]
    else if(u.pathname===service+'/parametresCentre/liquidacioIVA') payload={valor:'F',idCentre:555}
    else if(u.pathname===service+'/factura/validate') {assert.equal(request.method,'PUT');await request.json();if(invoiceValidationRejected) return Response.json({message:'Error intencional del servidor'},{status:400});payload=invoiceValidationFails?{dataRegistre:'Error intencional de validació'}:{}}
    else if(u.pathname===service+'/factura/desa') {
      assert.equal(request.method,'PUT');const invoice=await request.json()
      if(desaFails) return new Response('HTTP method PUT is not supported by this URL',{status:405,headers:{'Content-Type':'text/html'}})
      assert(invoice.identificadorDocProveidor.startsWith('CSC-POC-'));assert(invoice.identificadorDocProveidor.length<=20,invoice.identificadorDocProveidor);assert.equal(invoice.pressupost.id,123);assert.equal(invoice.pressupost.idCentre,555)
      assert.equal(invoice.partidasFactura[0].partidaPressupost.id,61);assert.equal(invoice.partidasFactura[0].centreCost?.id,71);assert.equal(invoice.vencimentsFactura[0].tipusPagament,'TR');assert.equal(invoice.vencimentsFactura[0].compteBancari.id,51);assert.equal(invoice.liquidat,'F');assert.equal(invoice.vencimentsFactura[0].liquidat,'F');assert.equal(Object.hasOwn(invoice,'id'),false)
      assert(!savedPortalInvoices.some(i=>i.identificadorDocProveidor===invoice.identificadorDocProveidor))
      savedPortalInvoices.push({...invoice,id:9000+savedPortalInvoices.length,codiGeneratSistema:'FC-PORTAL-POC-'+savedPortalInvoices.length});payload={}
    } else if(/^\/bfgh\/AppJava\/bfgh_gesteco\/services\/factura\/\d+$/.test(u.pathname)) payload=savedPortalInvoices.find(i=>i.id===Number(u.pathname.split('/').pop()))
    // Dashboard reads: execution, treasury, journal, incomes and the e-invoice tray.
    else if(u.pathname===service+'/pressupost/estat/123') { assert.equal(request.method,'GET'); payload={totalPressupostatIngres:2000,totalImputatIngressos:1500,totalDisponibleIngressos:500,totalPressupostatDespesa:2000,totalImputatDespeses:2100,totalDisponibleDespeses:-100,equilibriPressupost:0,totalPagaments:900,pagamentsAnyPressupost:900,pagamentsExercisisAnteriors:0,totalCobraments:1200,cobramentsAnyPressupost:1200,cobramentsExercisisAnteriors:0,partidaPressupostsIngressos:[{codiPartida:'I/410000902',nomPartida:'Del Departament',codFinalista:'',importPressupostat:2000,importImputat:1500,importCompromes:1500,saldoPartida:500,esSubPartida:'F'}],partidaPressupostsDespeses:[{codiPartida:'D/220000100/4210',nomPartida:'Material',codFinalista:'',importPressupostat:2000,importImputat:2100,importCompromes:2100,saldoPartida:-100,esSubPartida:'F'},{codiPartida:'D/220000100/4210.01',nomPartida:'Material del fons',codFinalista:'FONS2026',importPressupostat:2000,importImputat:2100,importCompromes:2100,saldoPartida:-100,esSubPartida:'T'}]} }
    else if(u.pathname===service+'/compteBancari/findByCentre') { assert.equal(request.method,'GET'); payload=[{id:51,codiCompte:'BC1',nomDescriptiuCompte:'Compte general de prova',saldo:1000,estat:'A',comptePrincipal:'T',numeroCompte:'0000001234',codiIban:'ES00-must-not-cross-bridge'}] }
    else if(u.pathname===service+'/caixaEfectiu/cerca') { assert.equal(request.method,'GET'); payload=[{id:52,codCompte:'CX1',descripcio:'Caixa de prova',saldo:50,activa:'A',responsable:'Persona de prova'}] }
    else if(u.pathname===service+'/consulta/ldo') { assert.equal(request.method,'GET'); assert.equal(u.searchParams.get('dataInici'),'01/01/2026'); const m=(n,t,d,c,v)=>({numeroMoviment:n,tipusOperacio:t,dataMoviment:Date.UTC(2026,d[0],d[1],12),codiComptePartida:c,import_:v,anulat:'F',descripcioMoviment:'Moviment de prova '+n}); payload=[m(1,'CI',[1,10],'BC1',1200),m(1,'CI',[1,10],'AP1',-1200),m(2,'PF',[2,5],'BC1',-900),m(2,'PF',[2,5],'PR1',900),m(3,'TBX',[2,6],'BC1',-50),m(3,'TBX',[2,6],'CX1',50)] }
    else if(u.pathname===service+'/ingres/cerca/filtre') { assert.equal(request.method,'POST'); const filter=await request.json(); assert.equal(filter.idPressupost,123); payload=[{id:88,codiGeneratSistema:'IG202600000001',aportador:{nom:'Aportador de prova'},descripcio:'Ingrés de prova',importTotalFinal:1200,importEfectuat:1200,importPendent:0,anulat:'F',tipusDocument:'I',dataRegistre:1770681600000}] }
    else if(u.pathname===service+'/facturaElectronica/pendents') { assert.equal(request.method,'GET'); payload=[{id:1}] }
    else throw Error('Unexpected adapter endpoint: '+u.pathname)
    return Response.json(trainingBadShape?{unexpected:true}:payload)
  })
  try {
    await click('Configuració');await until(()=>portal.isDestroyed(),'close local portal before adapter fixture')
    url=trainingOrigin+'/bfgh/gestioeconomica/#/'
    await evalApp("location.hash='/eines/sfera'")
    portal=await until(()=>webContents.getAllWebContents().find(w=>!w.isDestroyed()&&w.getURL().startsWith(url.split('#')[0])),'training fixture opens')
    await until(()=>!portal.isLoading(),'training fixture loads')
    await evalApp("location.hash='/eines/sfera/dades'")
    await until(()=>evalApp("!!document.querySelector('.dash')"),'Dashboard route')
    assert.equal(portal.isDestroyed(),false)
    await until(()=>win.contentView.children.filter(v=>'webContents'in v&&v.webContents===portal).length===0,'portal suspended below the dashboard')
    // The dashboard reads by itself on arrival; treasury is 1 000 € in the bank plus 50 € in cash.
    await until(()=>evalApp("document.querySelector('.kpis:not(.skeleton)')?.textContent.includes('1.050')"),'dashboard populated')
    assert.equal(await evalApp("document.querySelector('.page-lead')?.textContent.includes('08000001')"),true)
    assert.equal(await evalApp("document.querySelector('.alerts')?.textContent.includes('excés')"),true)
    await until(()=>evalApp("!document.querySelector('.controls .btn-outline').disabled"),'dashboard idle')
    const dash=await evalApp("window.cosecreDesktop.sferaDashboard.load({budgetId:999})")
    assert.equal(dash.ok,true);assert.equal(dash.data.budget.id,123,'an unknown budget falls back to the centre’s own')
    assert.equal(dash.data.treasury.total,1050);assert.equal(dash.data.months[1].collected,1200);assert.equal(dash.data.months[2].paid,900,'transfer between bank and cash left out')
    assert.equal(dash.data.treasury.series[0].balance,750);assert.equal(dash.data.treasury.series.at(-1).balance,1050)
    assert.equal(dash.data.lines.filter(l=>l.kind==='D'&&l.available<0).length,2);assert.equal(dash.data.eInvoicesPending,1)
    assert.equal(dash.data.incomes[0].contributor,'Aportador de prova');assert.equal(dash.data.invoices[0].pending,121)
    assert.equal(JSON.stringify(dash).includes('must-not-cross-bridge'),false);assert.equal(JSON.stringify(dash).includes('synthetic-sfera-token'),false)
    assert.deepEqual(dash.data.requests.map(r=>r.method).sort(),['GET','GET','GET','GET','GET','GET','POST','POST'])
    for(const input of [{budgetId:-1},{budgetId:'123'},{url:'https://evil.invalid'},{dataset:'budgets'}]) assert.equal(await evalApp(`window.cosecreDesktop.sferaDashboard.load(${JSON.stringify(input)}).then(()=>false,()=>true)`),true)
    assert.equal((await evalApp("window.cosecreDesktop.sferaDashboard.selectCentre('not-a-centre')")).ok,false)
    record('Dashboard: one read of execution, treasury, journal, invoices and incomes; transfers excluded from flows, balance walked back from today, no IBAN or token across the bridge, inputs refused')
    const budgetResult=await evalApp("window.cosecreDesktop.sferaData.query({dataset:'budgets'})")
    assert.equal(budgetResult.totalRows,1);assert.equal(budgetResult.requests[0].status,200);assert(budgetResult.durationMs>=0)
    const providerResult=await evalApp("window.cosecreDesktop.sferaData.query({dataset:'suppliers'})")
    assert.equal(providerResult.rows[0].nom,'Proveïdor de prova');assert.equal(Object.hasOwn(providerResult.rows[0],'token'),false)
    const invoiceResult=await evalApp("window.cosecreDesktop.sferaData.query({dataset:'invoices',budgetId:123})")
    assert.equal(invoiceResult.rows[0].proveidor,'Proveïdor de prova');assert.equal(invoiceResult.rows[0].importTotalFinal,121)
    assert.equal(invoiceResult.requests.length,2)
    record('Data explorer: same sandboxed session, real HTTP reads, summary, tables and per-request timing')
    const realCatalog=await evalApp("window.cosecreDesktop.sferaInvoices.catalog()")
    assert.equal(realCatalog.banks[0].label,'Compte general de prova');assert.equal(realCatalog.partidas[0].id,61)
    const realInput={budgetId:123,bankId:51,movements:[{id:'M010',date:'2026-10-12',description:'COSECRE POC · native writer integration test',amount:-1,supplierId:1,partidaId:61}]}
    const plan=await evalApp(`window.cosecreDesktop.sferaInvoices.prepare(${JSON.stringify(realInput)})`)
    assert.equal(plan.invoices[0].importTotalFinal,1)
    const result=await evalApp(`window.cosecreDesktop.sferaInvoices.create(${JSON.stringify(plan.id)})`)
    assert.equal(result.error,null);assert.equal(result.records.length,1);assert.equal(result.records[0].id,9000)
    assert(result.requests.some(r=>r.method==='PUT'&&r.path.endsWith('/factura/desa')))
    const repeated=await evalApp(`window.cosecreDesktop.sferaInvoices.create(${JSON.stringify(plan.id)})`)
    assert.equal(repeated.error,null);assert.equal(savedPortalInvoices.length,1);assert.equal(repeated.requests.some(r=>r.method==='PUT'),false)
    const failingPlan=await evalApp(`window.cosecreDesktop.sferaInvoices.prepare(${JSON.stringify(realInput)})`)
    invoiceValidationFails=true
    const failingResult=await evalApp(`window.cosecreDesktop.sferaInvoices.create(${JSON.stringify(failingPlan.id)})`)
    assert(failingResult.error.includes('no valida'));assert.equal(savedPortalInvoices.length,1)
    invoiceValidationFails=false
    const rejectedPlan=await evalApp(`window.cosecreDesktop.sferaInvoices.prepare(${JSON.stringify(realInput)})`)
    invoiceValidationRejected=true
    const rejectedResult=await evalApp(`window.cosecreDesktop.sferaInvoices.create(${JSON.stringify(rejectedPlan.id)})`)
    assert(rejectedResult.error.includes('HTTP 400')&&rejectedResult.error.includes('Error intencional del servidor'),rejectedResult.error);assert.equal(savedPortalInvoices.length,1)
    assert(rejectedResult.requests.some(r=>r.path.endsWith('/factura/validate')&&r.status===400))
    invoiceValidationRejected=false
    record('Native invoice writer: real HTTP catalog/validate/save/readback through scoped IPC; pending invoices, owned review plans, duplicate prevention, validation rejection and HTTP error reasons (intercepted portal fixture)')
    const exportPayload=(n)=>({rapel:false,dataDocument:'12/10/2026',dataRegistre:'12/10/2026',descripcio:'COSECRE POC · runner',observacions:null,despesaSimplificada:'F',identificadorDocCentre:null,identificadorDocProveidor:n,importIrpf:0,importIvaTotal:0,importPendent:1,importTotalFinal:1,tipusDespesa:'1',tipusDocument:'F',pressupost:{id:123,any:2026,idCentre:555},proveidor:{id:1},liquidat:'F',partidasFactura:[{partidaPressupost:{id:61},centreCost:{id:71},importBase:1,importIrpf:'0.00',importBaseProrrata:1,reservaDespesa:null}],vencimentsFactura:[{anulat:'F',liquidat:'F',dataVenciment:'12/11/2026',import_:1,tipusPagament:'TR',numeroXec:null,compteBancari:{id:51},descripcio:'Pagament'}]})
    const exportContext={environment:'training',centre_code:'08000001',remote_centre_id:555,remote_budget_id:123,financial_year:2026,vat_settlement:false}
    const planId=(n)=>`00000000-0000-4000-8000-${String(n).padStart(12,'0')}`
    const runExport=(id,item=1)=>evalApp(`window.cosecreDesktop.sferaExport.run(${JSON.stringify(id)},${typeof item==='number'?item:JSON.stringify(item)})`)
    exportHub.plans.set(planId(1),{attempt:0,payload:exportPayload('CSC-POC-hub001-M001'),context:exportContext})
    const exported=await runExport(planId(1))
    assert.equal(exported.outcome,'succeeded',exported.error);assert.equal(exported.error,null)
    const exportReport=exportHub.results.at(-1)
    assert.equal(exportReport.outcome,'succeeded');assert.equal(exportReport.attempt_id,1);assert(Number.isSafeInteger(exportReport.remote_id))
    assert.deepEqual(exportReport.readback,{supplier_remote_id:1,total:'1.00',remote_budget_id:123,document_number:'CSC-POC-hub001-M001'})
    // The same item again is found in the portal: uncertain, never saved twice.
    const savedBeforeExport=savedPortalInvoices.length
    const repeatedExport=await runExport(planId(1))
    assert.equal(repeatedExport.outcome,'uncertain');assert.equal(savedPortalInvoices.length,savedBeforeExport);assert(repeatedExport.requests.every(r=>r.method!=='PUT'))
    // A plan for another centre, or a payload over Esfer@'s limits, is refused before any write.
    exportHub.plans.set(planId(2),{attempt:0,payload:exportPayload('CSC-POC-hub002-M001'),context:{...exportContext,centre_code:'08000099'}})
    const otherCentre=await runExport(planId(2))
    assert.equal(otherCentre.outcome,'failed');assert(otherCentre.requests.every(r=>r.method!=='PUT'));assert.equal(exportHub.results.at(-1).no_effect_confirmed,true);assert(/centre/.test(otherCentre.error))
    exportHub.plans.set(planId(3),{attempt:0,payload:exportPayload('COSECRE-POC-tooLong-M001'),context:exportContext})
    const tooLong=await runExport(planId(3))
    assert.equal(tooLong.outcome,'failed');assert(tooLong.requests.every(r=>r.method!=='PUT'))
    // desa fails server-side (the generic 405): a read shows nothing was saved, so it is a confirmed failure.
    desaFails=true
    exportHub.plans.set(planId(4),{attempt:0,payload:exportPayload('CSC-POC-hub004-M001'),context:exportContext})
    const desaFailed=await runExport(planId(4)); desaFails=false
    assert.equal(desaFailed.outcome,'failed');assert.equal(exportHub.results.at(-1).no_effect_confirmed,true);assert(desaFailed.requests.some(r=>r.path.endsWith('/factura/desa')&&r.status===405))
    // The Hub cannot take the report: the person is told to recover and reconcile.
    exportHub.resultFails=true
    exportHub.plans.set(planId(5),{attempt:0,payload:exportPayload('CSC-POC-hub005-M001'),context:exportContext})
    const lostReport=await runExport(planId(5)); exportHub.resultFails=false
    assert.equal(lostReport.outcome,'succeeded');assert(/concilia/.test(lostReport.error))
    // Only IDs cross the bridge.
    await assert.rejects(runExport('not-a-plan'));await assert.rejects(runExport(planId(1),{payload:1}))
    record('Hub export runner: payload only from the Hub, session centre/budget and limits checked before writing, existing invoice → uncertain, desa failure confirmed by readback, lost report flagged; only IDs cross the bridge')
    // Reconcile by reading the portal: the saved one is found with its readback, the failed one is absent.
    exportHub.plans.get(planId(1)).state='uncertain'; exportHub.plans.get(planId(4)).state='uncertain'
    const reconciledFound=await evalApp(`window.cosecreDesktop.sferaExport.reconcile(${JSON.stringify(planId(1))},1)`)
    assert.equal(reconciledFound.outcome,'succeeded');assert(reconciledFound.requests.every(r=>r.method!=='PUT'))
    assert.deepEqual(exportHub.reconciles.at(-1).readback,{supplier_remote_id:1,total:'1.00',remote_budget_id:123,document_number:'CSC-POC-hub001-M001'});assert.equal(exportHub.reconciles.at(-1).found,true)
    const reconciledAbsent=await evalApp(`window.cosecreDesktop.sferaExport.reconcile(${JSON.stringify(planId(4))},1)`)
    assert.equal(reconciledAbsent.outcome,'failed');assert.deepEqual(exportHub.reconciles.at(-1),{found:false})
    exportHub.plans.get(planId(4)).state='approved'
    await assert.rejects(evalApp(`window.cosecreDesktop.sferaExport.reconcile(${JSON.stringify(planId(4))},1)`))
    record('Hub export reconcile: reads the portal only; found → readback to the Hub, absent → not found; only uncertain items')
    // Read-only diagnostic of the session, with a synthetic invoice through the Hub preflight.
    const putsBefore=dataRequests.filter(r=>r.method==='PUT').length
    const diagnosis=await evalApp('window.cosecreDesktop.sferaExport.diagnose()')
    assert.equal(diagnosis.centre,'08000001');assert.equal(diagnosis.ready,true,JSON.stringify(diagnosis.checks))
    const checkIds=diagnosis.checks.map(c=>c.id)
    for(const id of ['session','budget','vat','cost-centres','banks','suppliers','search','hub','preflight']) assert(checkIds.includes(id),id)
    assert.equal(dataRequests.filter(r=>r.method==='PUT').length,putsBefore);assert(diagnosis.requests.every(r=>r.method!=='PUT'))
    const sample=exportHub.preflights.at(-1)
    assert.equal(sample.context.centre_code,'08000001');assert.equal(sample.context.remote_budget_id,123);assert.equal(sample.invoices[0].lines[0].cost_centre_remote_id,71);assert.equal(sample.invoices[0].due_dates[0].bank_account_remote_id,51)
    record('Export diagnostic: session, budget, VAT, cost centres, banks, suppliers, search and Hub capability checked read-only; synthetic invoice through the Hub preflight')
    // The plans screen lists the Hub's plans and shows the selected one.
    await evalApp(`location.hash='/eines/sfera/plans?pla=${planId(1)}'`)
    await until(()=>evalApp("document.body.textContent.includes('Plans d’exportació') && !!document.querySelector('[data-item]')"),'plans view')
    const planRows=await evalApp("document.querySelectorAll('.plan-row').length")
    assert.equal(planRows,exportHub.plans.size)
    assert(await evalApp("document.querySelector('[data-item]').textContent.includes('CSC-POC-hub001-M001')"))
    // Moving between Esfer@ screens keeps the hidden portal session.
    await evalApp("location.hash='/eines/sfera/dades'")
    await until(()=>evalApp("location.hash.startsWith('#/eines/sfera/dades') && !document.querySelector('[data-item]')"),'back to the dashboard')
    assert(!portal.isDestroyed(),'portal kept between Esfer@ screens')
    record('Plans screen: Hub plans listed, selected plan and its items shown; portal session kept when moving between Esfer@ screens')
    const before=dataRequests.length
    const invalidBudget=await evalApp("window.cosecreDesktop.sferaData.query({dataset:'invoices',budgetId:999})")
    assert(invalidBudget.error);assert.equal(dataRequests.length,before+1)
    for(const input of [{dataset:'saveInvoice'},{dataset:'budgets',url:'https://evil.invalid'},{dataset:'budgets',method:'PUT'},{dataset:'invoices',budgetId:-1}]) assert.equal(await evalApp(`window.cosecreDesktop.sferaData.query(${JSON.stringify(input)}).then(()=>false,()=>true)`),true)
    record('Data bridge: unknown operations and caller-supplied URLs/methods refused; invoice budget checked against centre')
    trainingExpired=true
    const expired=await evalApp("window.cosecreDesktop.sferaData.query({dataset:'suppliers'})")
    assert(expired.error);assert.equal(expired.rows.length,0);assert.equal(expired.requests.length,1)
    trainingExpired=false;trainingBadShape=true
    const changed=await evalApp("window.cosecreDesktop.sferaData.query({dataset:'budgets'})")
    assert(changed.error.includes('format'));assert.equal(changed.rows.length,0)
    trainingBadShape=false
    trainingRedirect=true
    const redirected=await evalApp("window.cosecreDesktop.sferaData.query({dataset:'budgets'})")
    assert(redirected.error);assert([null,302].includes(redirected.requests[0].status));assert.equal(outsideTrainingRequests,0)
    trainingRedirect=false
    trainingCentreChange=true
    const centreChanged=await evalApp("window.cosecreDesktop.sferaData.query({dataset:'budgets'})")
    assert(centreChanged.error.includes('centre'));assert.equal(centreChanged.rows.length,0)
    trainingCentreChange=false
    await portal.executeJavaScript("window.AppClient.CENTRE_SESSIO.codiExtern='08000001'")
    record('Data explorer: expired authentication and changed response schema produce errors without stale data')
    record('Portal-specific numeric headers preserved; data redirects refused without forwarding access headers')
    record('Centre changing during a query clears results instead of mixing contexts')
    await click('Factures')
    await until(()=>evalApp("!!document.querySelector('.records .row')"),'invoice rows')
    await evalApp("document.querySelector('.records .row').click()")
    await until(()=>evalApp("document.querySelector('.records .detail')?.textContent.includes('121')"),'invoice details')
    await writeFile(join(output,'explorer-fixture.png'),await(await win.capturePage()).toPNG())
    await click('Navegador')
    await until(()=>evalApp("!!document.querySelector('.browser-surface')"),'return to same portal')
    assert.equal(portal.isDestroyed(),false)
    await click('Configuració');await until(()=>portal.isDestroyed(),'leave Esfer@ disposes suspended context')
    record('Explorer navigation: centre preserved between its two views; leaving tool disposes contents')
  } finally {url=localPortalUrl;await partition1.protocol.unhandle('https')}
  await openPortal()
  const gicar = 'https://autenticaciogicar5.extranet.gencat.cat'
  let automaticSubmissions = 0
  await portal.session.protocol.handle('https', async request => {
    assert.equal(new URL(request.url).origin, gicar)
    if (request.method === 'POST') {
      const fields = await request.formData()
      assert.equal(fields.get('username'), 'gicar-test-user')
      assert.equal(fields.get('password'), fixturePassword)
      automaticSubmissions++
      return new Response('<title>GICAR de prova</title><h1>Identificació de prova rebuda</h1>', { headers: { 'Content-Type': 'text/html' } })
    }
    return new Response(`<title>GICAR de prova</title><form id="kc-form-login" method="post" action="${gicar}/realms/gicar-ad/login-actions/authenticate"><input name="username" id="username"><input type="password" name="password" id="password"><input type="submit" name="login" id="kc-login"></form>`, { headers: { 'Content-Type': 'text/html' } })
  })
  try {
    await portal.loadURL(gicar + '/realms/gicar-ad/protocol/saml')
    await until(() => automaticSubmissions === 1, 'automatic GICAR form submission')
    await sleep(300)
    assert.equal(automaticSubmissions, 1)
    record('Automatic login: fixed GICAR form submitted once with personal credentials (intercepted fixture, no external transmission)')
  } finally { await portal.session.protocol.unhandle('https') }
  await click('Inici'); await until(() => portal.getURL() === url, 'return after login fixture')
  const portalCallsBeforePoc=requests.filter(r=>r.path.startsWith('/portal')).length
  await evalApp("location.hash='/eines/sfera/prova-extractes'")
  await until(()=>evalApp("document.body.textContent.includes('Prova sintètica local')"),'synthetic invoice PoC route')
  await until(()=>win.contentView.children.filter(v=>'webContents'in v&&v.webContents===portal).length===0,'PoC retains the portal hidden')
  await click('Preparar factures')
  await until(()=>evalApp("document.body.textContent.includes('2 factures preparades')"),'two invoice drafts')
  assert.equal(await evalApp("document.body.textContent.includes('M003: ingrés')"),true)
  assert.equal(await evalApp("document.body.textContent.includes('160,95')"),true)
  await click('Executar prova sintètica')
  await until(()=>evalApp("document.body.textContent.includes('2 factures creades i rellegides')"),'mock invoice creation and readback')
  assert.equal(await evalApp("document.body.textContent.includes('FC-POC-0001') && document.body.textContent.includes('FC-POC-0002')"),true)
  await evalApp("(()=>{const d=document.querySelectorAll('.poc details');d[d.length-1].open=true;[...document.querySelectorAll('h2')].find(e=>e.textContent.includes('Factures creades')).scrollIntoView({block:'center'});})()")
  await sleep(250)
  await writeFile(join(output,'invoice-poc-fixture.png'),await(await win.capturePage()).toPNG())
  await click('Executar prova sintètica')
  await until(()=>evalApp("document.body.textContent.includes('ja creada, no es duplica')"),'PoC duplicate prevention')
  assert.equal(await evalApp("[...document.querySelectorAll('h2')].find(e=>e.textContent.includes('Factures creades'))?.parentElement.querySelectorAll('tbody tr').length"),2)
  assert.equal(requests.filter(r=>r.path.startsWith('/portal')).length,portalCallsBeforePoc)
  record('Synthetic statement PoC: three fictitious movements → two invoice DTOs, income excluded, validation/save/readback, no portal calls or duplicate invoices')
  await evalApp("(()=>{const e=document.querySelector('[aria-label=\"Import M001\"]');e.value='0';e.dispatchEvent(new Event('input',{bubbles:true}));})()")
  await click('Preparar factures')
  await until(()=>evalApp("document.querySelector('[role=alert]')?.textContent.includes('no vàlides')"),'invalid statement does not create invoices')
  record('Synthetic statement PoC: invalid movements rejected before any create operation')
  await openPortal()
  await context('local-admin-user2')
  assert(portal.isDestroyed())
  await openPortal()
  assert.notEqual(portal.session, partition1)
  assert.equal((await portal.session.cookies.get({ name: 'portal_session' })).length, 0)
  record('Account switch destroys contents and separates cookies')
  const otherCredentials = await evalApp("window.cosecreDesktop.browser.credentialsStatus('sfera')")
  assert.equal(otherCredentials.username, '')
  assert.equal(otherCredentials.configured, false)
  record('Each secretary has separate credentials; another account cannot read them')
  await context('local-admin-user1')
  await openPortal()
  assert.equal(portal.session, partition1)
  record('Original account recovers its own persistent session')
  secondHub = createServer(hub.listeners('request')[0])
  await new Promise(done => secondHub.listen(0, '127.0.0.1', done))
  const otherHub = `http://127.0.0.1:${secondHub.address().port}/api/v1`
  await switchHub(otherHub)
  await openPortal()
  assert.notEqual(portal.session, partition1)
  assert.equal((await portal.session.cookies.get({ name: 'portal_session' })).length, 0)
  assert.equal((await evalApp("window.cosecreDesktop.browser.credentialsStatus('sfera')")).configured, false)
  await switchHub(hubUrl)
  await openPortal()
  assert.equal(portal.session, partition1)
  assert.equal((await portal.session.cookies.get({ name: 'portal_session' })).length, 1)
  record('Hub switch separates both session cookies and personal credentials, and restores the original context')
  const ownCredentials = await evalApp("window.cosecreDesktop.browser.credentialsStatus('sfera')")
  assert.equal(ownCredentials.configured, true)
  await evalApp("window.cosecreDesktop.browser.removeCredentials('sfera')")
  assert.equal((await evalApp("window.cosecreDesktop.browser.credentialsStatus('sfera')")).configured, false)
  record('Personal credentials can be removed without returning their secret')
  await context('local-professor-user1')
  await until(() => evalApp("!document.body.textContent.includes('Esfer@')"), 'professor has no Esfer@ navigation')
  const denied = await evalApp("window.cosecreDesktop.browser.open('sfera').then(()=>false,()=>true)")
  assert(denied)
  assert.equal(await evalApp("window.cosecreDesktop.sferaData.query({dataset:'budgets'}).then(()=>false,()=>true)"),true)
  record('Professor: tool hidden, main-process browser access refused')
  await context('local-staff-user1')
  await openPortal()
  assert.equal(await evalApp("!!document.querySelector('a[href=\"#/settings?tab=sfera\"]')"), false)
  await click('El meu accés')
  await until(() => evalApp("!!document.querySelector('.personal-dialog input[type=password]')"), 'staff personal access')
  assert.equal((await evalApp("window.cosecreDesktop.browser.credentialsStatus('sfera')")).configured, false)
  await click('Tancar')
  record('Administrative account: own credentials accessible, shared configuration inaccessible')
  configured = false
  await context('local-admin-user1')
  await until(() => evalApp("document.body.textContent.includes('Configura') && document.body.textContent.includes('accés a Esfer@')"), 'missing configuration')
  record('Missing URL: configure-access empty state')
  configured = true
  await context('local-admin-user1')
  await openPortal()
  await portal.executeJavaScript("location.href='http://127.0.0.1:1/unavailable'")
  await until(() => evalApp("document.querySelector('[role=alert]')?.textContent.includes('carregar el portal')"), 'load error state')
  record('Portal load failure is visible with retry')
  await click('Inici'); await until(() => portal.getURL() === url, 'recover from load failure')
  await writeFile(join(output, 'portal.png'), await (await portal.capturePage()).toPNG())
  await writeFile(join(output, 'window.png'), await (await win.capturePage()).toPNG())
  assert(requests.filter(r => r.path.startsWith('/portal')).every(r => r.authorization === null))
  record('Hub bearer tokens are never sent to portal requests')
  webWindow = new BrowserWindow({ show: false, webPreferences: { sandbox: true, nodeIntegration: false, contextIsolation: true } })
  await webWindow.loadURL(origin)
  await webWindow.webContents.executeJavaScript("localStorage.setItem('cosecre.accessToken','local-admin-user1'); localStorage.setItem('cosecre.refreshToken','local-refresh')")
  await webWindow.loadURL(origin + '/eines/sfera').catch(error => { if (!['ERR_FAILED', 'ERR_ABORTED'].includes(error.code)) throw error })
  await until(async () => (await webWindow.webContents.executeJavaScript("!!document.querySelector('.account') && location.pathname === '/registre'")), 'web rejects desktop route')
  assert.equal(await webWindow.webContents.executeJavaScript("document.body.textContent.includes('Esfer@')"), false)
  await webWindow.loadURL(origin + '/eines/sfera/dades').catch(error => { if (!['ERR_FAILED', 'ERR_ABORTED'].includes(error.code)) throw error })
  await until(async () => (await webWindow.webContents.executeJavaScript("!!document.querySelector('.account') && location.pathname === '/registre'")), 'web rejects data route')
  await webWindow.loadURL(origin + '/settings?tab=sfera').catch(error => { if (!['ERR_FAILED', 'ERR_ABORTED'].includes(error.code)) throw error })
  await until(async () => (await webWindow.webContents.executeJavaScript("document.body.textContent.includes('Full de càlcul')")), 'web settings load')
  assert.equal(await webWindow.webContents.executeJavaScript("document.body.textContent.includes('Esfer@')"), false)
  webWindow.destroy()
  record('Web: no Esfer@ sidebar, settings tab or browser route')
  if (process.env.SFERA_CHECK_PORTAL) {
    await click('Configuració')
    await until(() => portal.isDestroyed(), 'close fixture before real portal')
    url = process.env.SFERA_CHECK_PORTAL
    await evalApp("location.hash='/eines/sfera'")
    portal = await until(() => webContents.getAllWebContents().find(wc => wc !== win.webContents && !wc.isDestroyed() && wc.getURL().startsWith('https:')), 'real portal opens')
    await until(() => !portal.isLoading(), 'real portal load')
    const live = { origin: new URL(portal.getURL()).origin, title: portal.getTitle(), authenticated: false }
    await writeFile(join(output, 'real-access.json'), JSON.stringify(live, null, 2))
    await writeFile(join(output, 'real-window.png'), await (await win.capturePage()).toPNG())
    record('Real training portal: anonymous GICAR login in embedded view; authenticated operations unverified')
  }
  await writeFile(join(output, 'verification.json'), JSON.stringify({ electron: process.versions.electron, checks, portal: process.env.SFERA_CHECK_PORTAL ? 'local fixture plus anonymous training login; authenticated Esfer@ operations not verified' : 'controlled local fixture; real Esfer@ not verified' }, null, 2))
  console.log(JSON.stringify({ passed: checks.length, checks, artifacts: output }, null, 2))
  if (process.env.SFERA_CHECK_HOLD === '1') { console.log('Visible fixture ready; close the window to end.'); await new Promise(done => win.on('closed', done)) }
} catch (error) {
  console.error(error)
  if (win && !win.isDestroyed()) console.log('layout', await evalApp("({hidden:document.hidden, rect:document.querySelector('.browser-surface')?.getBoundingClientRect().toJSON(), overlays:[...document.querySelectorAll('[role=dialog], [role=menu], .overlay, .scrim, dialog[open], .popover')].filter(e=>e.getClientRects().length).map(e=>e.className)})"))
  if (webWindow && !webWindow.isDestroyed()) console.log('web', webWindow.webContents.getURL(), await webWindow.webContents.executeJavaScript('document.body.innerText'))
  console.log('main url', win?.webContents.getURL(), 'portal', portal?.isDestroyed() ? 'destroyed' : portal?.getURL())
  if (win && !win.isDestroyed()) console.error(await evalApp('document.body.innerText').catch(() => ''))
  process.exitCode = 1
} finally {
  for (const w of BrowserWindow.getAllWindows()) w.destroy()
  if (secondHub) { secondHub.closeAllConnections(); await new Promise(done => secondHub.close(done)) }
  hub.closeAllConnections()
  await new Promise(done => hub.close(done))
  await rm(data, { recursive: true, force: true })
  app.exit(process.exitCode ?? 0)
}

}
void main().catch((error) => { console.error(error); app.exit(1) })
