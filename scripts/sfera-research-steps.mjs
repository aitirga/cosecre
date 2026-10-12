/** Author-written read-only exploration steps; not supplied by the remote page.
 *  The centre to select comes from SFERA_RESEARCH_CENTRE (its external code). */
export async function run({ win, portal, snapshotCode, save, until, sleep, present }) {
  const sources = await portal.executeJavaScript(`Promise.all([...document.scripts].filter(s=>s.src.includes('/resources/js/moduls/gestioeconomica/')).map(async s=>({url:s.src, source:(await (await fetch(s.src)).text()).slice(0,250000)})))`)
  await save('client-sources', sources)
  console.log(JSON.stringify({ sourceFiles:sources.map(s=>({name:s.url.split('/').pop().split('?')[0],bytes:s.source.length})), framework:await portal.executeJavaScript("window.angular?.version?.full") }, null, 2))
  const centre = await portal.executeJavaScript(`(() => {
    const e=[...document.querySelectorAll('[data-ng-click="setCentreActiuModal(centre)"]')].find(e=>e.closest('tr')?.innerText.includes(${JSON.stringify(process.env.SFERA_RESEARCH_CENTRE ?? '')}));
    if (!e) return {needed:false};
    const scope=window.angular?.element(e).scope();
    if (!scope || typeof scope.setCentreActiuModal !== 'function') return {needed:true,scopeAvailable:!!scope};
    scope.$apply(()=>scope.setCentreActiuModal(scope.centre));
    return {needed:true,programmatic:true};
  })()`)
  await save('centre-selection', centre)
  if (centre.programmatic) {
    await until(()=>portal.executeJavaScript("[...document.querySelectorAll('table')].some(t=>t.innerText.includes('Exercici'))"), 'budget table')
    await sleep(500)
  }
  const snapshot = await portal.executeJavaScript(snapshotCode)
  await save('02-budgets', snapshot)
  console.log(JSON.stringify({ stage:'budgets', tables:snapshot.tables.map(t=>({headers:t.rows[0],rows:t.rows.length})), actions:snapshot.actions.length }))
  const budget = await portal.executeJavaScript(`(() => {
    const e=[...document.querySelectorAll('[data-ng-click="editarPressupost(row.any, row.id)"]')].find(e=>{const text=e.closest('tr')?.innerText||''; return text.includes('2026')&&text.includes('General')});
    if(!e) throw Error('2026 General budget not found');
    const scope=window.angular.element(e).scope();
    const result={id:scope.row.id,year:scope.row.any,method:typeof scope.editarPressupost};
    scope.$apply(()=>scope.editarPressupost(scope.row.any,scope.row.id));
    return result;
  })()`)
  await save('budget-context',budget)
  await until(()=>portal.executeJavaScript("location.hash.includes('/pressupost/')"), 'budget detail route')
  await sleep(1500)
  const overview=await portal.executeJavaScript(snapshotCode)
  await save('03-budget-detail',overview)
  console.log(JSON.stringify({stage:'budget-detail',context:budget,url:overview.url,actions:overview.actions.length}))
  await portal.executeJavaScript(`location.hash=${JSON.stringify('#/pressupost/')}+${JSON.stringify(budget.id)}+'/'+${JSON.stringify(budget.year)}+'/proveidorsdespeses/'`)
  await until(()=>portal.executeJavaScript("[...document.querySelectorAll('a,button')].some(e=>e.textContent.includes('Factures'))"), 'suppliers and invoices tabs')
  await sleep(1000)
  const providers=await portal.executeJavaScript(snapshotCode)
  await save('04-suppliers-expenses',providers)
  console.log(JSON.stringify({stage:'suppliers-expenses',url:providers.url,actions:providers.actions.length,tables:providers.tables.map(t=>({headers:t.rows[0],rows:t.rows.length}))}))
  const extraSources=await portal.executeJavaScript(`Promise.all(['proveidors/facturas/facturas_controller.js','proveidors/facturas/facturas_services.js','proveidors/facturas/facturas_gridbuilder_service.js','proveidors/proveidors_controller.js','pressupost/base_pressupost_controller.js','pressupost/base_pressupost_services.js'].map(async path=>{const url=location.origin+'/bfgh/resources/js/moduls/gestioeconomica/'+path+'?version=12.40.2_B000'; return {url,source:(await(await fetch(url)).text()).slice(0,300000)}}))`)
  await save('invoice-sources',extraSources)
  const budgetsApi=await portal.executeJavaScript(`(async()=>{const h=angular.element(document.body).injector().get('$http');const r=await h.get(AppClient.Config.obtenirUrlModul('bfgh_gesteco')+'/services/pressupost/centre');return {status:r.status,data:r.data}})()`)
  await save('budgets-api',budgetsApi)
  // Keep portal-specific auth headers in memory only, never in evidence or logs.
  const headers=await portal.executeJavaScript(`JSON.parse(JSON.stringify(angular.element(document.body).injector().get('$http').defaults.headers.common))`)
  const sessionResponse=await portal.session.fetch('https://formacio.bfgh.aplicacions.ensenyament.gencat.cat/bfgh/AppJava/bfgh_gesteco/services/pressupost/centre',{method:'GET',credentials:'include',headers})
  const body=await sessionResponse.text()
  await save('session-fetch-budget-proof',{status:sessionResponse.status,contentType:sessionResponse.headers.get('content-type'),data:body?JSON.parse(body):null,headerNames:Object.keys(headers)})
  const invoiceTab=await portal.executeJavaScript(`(() => {
    const e=[...document.querySelectorAll('[data-ng-click="setActiveTabProveidors($index)"]')].find(e=>e.textContent.trim()==='Factures');
    if(!e) return {found:false,labels:[...document.querySelectorAll('[data-ng-click="setActiveTabProveidors($index)"]')].map(e=>e.textContent.trim())};
    const s=window.angular.element(e).scope();s.$apply(()=>s.setActiveTabProveidors(s.$index));return {found:true};
  })()`)
  await save('invoice-tab',invoiceTab)
  await sleep(1500)
  const invoices=await portal.executeJavaScript(snapshotCode)
  await save('05-invoices',invoices)
  console.log(JSON.stringify({stage:'invoices',tab:invoiceTab,actions:invoices.actions.length,tables:invoices.tables.map(t=>({headers:t.rows[0],rows:t.rows.length}))}))
  const api=await portal.executeJavaScript(`(async()=>{const h=angular.element(document.body).injector().get('$http');const base=AppClient.Config.obtenirUrlModul('bfgh_gesteco');const s=angular.element(document.querySelector('[data-ng-controller="FacturesCtrl"]')).scope();const filter=angular.copy(s.factura1);filter.dataRegistreDesde=${JSON.stringify(budget.year+'/01/01')};filter.dataRegistreFinsa=${JSON.stringify(budget.year+'/12/31')};filter.idPressupost=${budget.id};const [suppliers,invoices]=await Promise.all([h.get(base+'/services/proveidor/cerca'),h.post(base+'/services/factura/cerca/filtre',filter)]);return {centre:{code:AppClient.CENTRE_SESSIO.codiExtern,name:AppClient.CENTRE_SESSIO.nom},filter,suppliers:suppliers.data,invoices:invoices.data};})()`)
  await save('datasets-api',api)
  if(api.invoices[0]?.id) {
    const id=api.invoices[0].id
    const schema=await portal.executeJavaScript(`(async()=>{const h=angular.element(document.body).injector().get('$http');const r=await h.get(AppClient.Config.obtenirUrlModul('bfgh_gesteco')+'/services/factura/${id}');return {status:r.status,id:${id},fields:Object.keys(r.data),arrays:Object.entries(r.data).filter(([,v])=>Array.isArray(v)).map(([key,v])=>({key,rows:v.length,fields:v[0]?Object.keys(v[0]):[]}))}})()`)
    await save('invoice-detail-schema',schema)
  }
  await portal.executeJavaScript(`(()=>{const e=document.getElementById('btnFactAddFact');const s=angular.element(e).scope();s.$apply(()=>s.addFacture(undefined,false));})()`)
  await sleep(2000)
  await save('06-new-invoice-form',await portal.executeJavaScript(snapshotCode))
  // Compare the bounded native request with the earlier full-header proof.
  const freshHeaders=await portal.executeJavaScript(`JSON.parse(JSON.stringify(angular.element(document.body).injector().get('$http').defaults.headers.common))`)
  await save('header-types',Object.fromEntries(Object.entries(freshHeaders).map(([key,value])=>[key,typeof value])))
  const nativeStart=performance.now()
  const nativeResponse=await portal.session.fetch('https://formacio.bfgh.aplicacions.ensenyament.gencat.cat/bfgh/AppJava/bfgh_gesteco/services/pressupost/centre',{method:'GET',credentials:'include',headers:freshHeaders,signal:AbortSignal.timeout(10000)})
  const nativeData=await nativeResponse.json()
  await save('native-after-form',{status:nativeResponse.status,count:nativeData.length,durationMs:performance.now()-nativeStart})
  await win.webContents.executeJavaScript("location.hash='/eines/sfera/dades'")
  await until(()=>win.webContents.executeJavaScript("!!document.querySelector('.explorer')"), 'Explorer renders')
  await sleep(500)
  const proofs=[]
  for(const dataset of ['budgets','suppliers','invoices']) {
    console.log('Explorer query: '+dataset)
    const result=await win.webContents.executeJavaScript(`window.cosecreDesktop.sferaData.query(${JSON.stringify({dataset,...(dataset==='invoices'?{budgetId:budget.id}:{})})})`)
    await save('explorer-'+dataset,result)
    proofs.push({dataset,centre:result.centre,count:result.totalRows,durationMs:result.durationMs,requests:result.requests,error:result.error})
    if(result.error) throw Error('Explorer: '+result.error)
  }
  await win.webContents.executeJavaScript("document.querySelector('.query-controls button').click()")
  await until(()=>win.webContents.executeJavaScript("!!document.querySelector('.summary')"),'Explorer real UI summary')
  for(const dataset of ['suppliers','invoices']) {
    await win.webContents.executeJavaScript(`(()=>{const s=document.querySelector('.query-controls select');s.value=${JSON.stringify(dataset)};s.dispatchEvent(new Event('change',{bubbles:true}));})()`)
    await sleep(100)
    await win.webContents.executeJavaScript("document.querySelector('.query-controls button').click()")
    await until(()=>win.webContents.executeJavaScript(`document.querySelector('.data-panel h2')?.textContent===${JSON.stringify(dataset==='suppliers'?'Proveïdors':'Factures')} && !document.querySelector('.query-controls button').disabled`),'Explorer '+dataset+' UI query')
  }
  await save('explorer-proof',proofs)
  console.log(JSON.stringify({stage:'queries',results:proofs}))
  await save('explorer-ui',{text:await win.webContents.executeJavaScript("document.querySelector('.explorer').innerText"),osPointerSimulation:false})
  const {writeFile}=await import('node:fs/promises')
  present()
  await win.webContents.executeJavaScript("document.querySelector('.request-panel').open=true")
  await sleep(600)
  await writeFile('output/playwright/sfera/research/explorer-real.png',await(await win.capturePage()).toPNG(),{mode:0o600})
}
