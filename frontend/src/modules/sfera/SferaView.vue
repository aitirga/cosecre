<script setup lang="ts">
import { keepsPortal } from './portal-routes'
import { nextTick, onBeforeUnmount, onMounted, ref } from 'vue'
import { onBeforeRouteLeave } from 'vue-router'
import { useAuth } from '../../composables/useAuth'
import { usePlatform } from '../../platform'
import type { BrowserAction, BrowserBounds, BrowserState } from '../../browser/contract'
import CredentialsPanel from './CredentialsPanel.vue'
import { portalUrl } from '../../browser/url'
import { getSettings, type SferaSettings } from './settings'
const auth = useAuth()
const browser = usePlatform().browser
const settings = ref<SferaSettings | null>(null)
const state = ref<BrowserState | null>(null)
const error = ref('')
const loading = ref(true)
const personalOpen = ref(false)
const busy = ref(false)
const surface = ref<HTMLElement | null>(null)
let alive = true
let frame = 0
let lastLayout = ''
let observer: MutationObserver | undefined
let resize: ResizeObserver | undefined
let unsubscribe: (() => void) | undefined
let preservePortal = false
onBeforeRouteLeave(to => { preservePortal = keepsPortal(to.name) })
function overlayOpen() {
  return [...document.querySelectorAll<HTMLElement>('[role="dialog"], [role="menu"], .overlay, .scrim, dialog[open], .popover')]
    .some((element) => element.getClientRects().length > 0)
}
// A native view sits above DOM content. Hide it before a menu/dialog appears;
// clip to the viewport on scroll, and restore its measured slot on dismissal.
function layout() {
  if (!alive || !state.value || !browser) return
  const rect = surface.value?.getBoundingClientRect()
  let bounds: BrowserBounds | null = null
  if (rect && !document.hidden && !overlayOpen()) {
    const x = Math.max(0, rect.left), y = Math.max(0, rect.top)
    bounds = { x, y, width: Math.max(0, Math.min(window.innerWidth, rect.right) - x), height: Math.max(0, Math.min(window.innerHeight, rect.bottom) - y) }
  }
  const next = JSON.stringify(bounds)
  if (next === lastLayout) return
  lastLayout = next
  void browser.layout(state.value.id, bounds).catch((e) => { if (alive) error.value = String(e) })
}
function scheduleLayout() { cancelAnimationFrame(frame); frame = requestAnimationFrame(layout) }
async function start() {
  loading.value = true; error.value = ''
  try {
    if (state.value) await browser?.close(state.value.id)
    state.value = null
    const loaded = await getSettings()
    if (!alive) return
    settings.value = loaded
    if (!loaded.access_url || !browser) return
    portalUrl(loaded.access_url)
    const opened = await browser.open('sfera')
    if (!alive) {
      if (preservePortal) await browser.layout(opened.id,null)
      else await browser.close(opened.id)
      return
    }
    state.value = opened
    lastLayout = ''
    await nextTick(); layout()
  } catch (e) { if (alive) error.value = e instanceof Error ? e.message : 'No es pot obrir Esfer@.' }
  finally { if (alive) loading.value = false }
}
async function command(action: BrowserAction) {
  if (!browser || !state.value || busy.value) return
  busy.value = true; error.value = ''
  try { state.value = await browser.command(state.value.id, action) }
  catch (e) { if (alive) error.value = e instanceof Error ? e.message : 'No es pot completar l’acció.' }
  finally { busy.value = false }
}
onMounted(() => {
  unsubscribe = browser?.onState((value) => { if (value.id === state.value?.id) state.value = value })
  observer = new MutationObserver(() => { if (overlayOpen()) layout(); else scheduleLayout() })
  observer.observe(document.body, { subtree: true, childList: true, attributes: true, attributeFilter: ['class', 'style', 'open'] })
  resize = new ResizeObserver(scheduleLayout)
  if (surface.value) resize.observe(surface.value)
  window.addEventListener('resize', scheduleLayout)
  window.addEventListener('scroll', layout, true)
  document.addEventListener('visibilitychange', layout)
  void start()
})
onBeforeUnmount(() => {
  alive = false; cancelAnimationFrame(frame); observer?.disconnect(); resize?.disconnect(); unsubscribe?.()
  window.removeEventListener('resize', scheduleLayout)
  window.removeEventListener('scroll', layout, true)
  document.removeEventListener('visibilitychange', layout)
  if (preservePortal && state.value) void browser?.layout(state.value.id, null).catch(() => {})
  else if (!preservePortal) void browser?.release('sfera').catch(() => {})
})
</script>
<template>
  <div class="sfera">
    <header class="page-head"><div><h1 class="page-title">Esfer@</h1><p class="page-lead">Navegador · {{ settings?.centre || 'Gestió econòmica' }}</p></div><RouterLink v-if="auth.isAdmin.value" class="btn btn-secondary" :to="{ name: 'settings', query: { tab: 'sfera' } }">Configuració</RouterLink></header>
    <div v-if="browser" class="toolbar" aria-label="Navegació d’Esfer@">
      <button class="btn btn-secondary" @click="personalOpen = true">El meu accés</button>
      <RouterLink class="btn btn-secondary" :to="{ name: 'sfera-data' }">Resum i dades</RouterLink>
      <button class="btn btn-secondary" :disabled="!state?.canGoBack || busy" @click="command('back')">Enrere</button>
      <button class="btn btn-secondary" :disabled="!state?.canGoForward || busy" @click="command('forward')">Endavant</button>
      <button class="btn btn-secondary" :disabled="!state || busy" @click="command('reload')">Recarregar</button>
      <button class="btn btn-secondary" :disabled="!state || busy" @click="command('home')">Inici</button>
      <button class="btn btn-secondary" :disabled="!state || busy" @click="command('login')">Identificar-me</button>
      <button class="btn btn-ghost" :disabled="!state || busy" @click="command('clear-session')">Esborrar sessió</button>
    </div>
    <p v-if="state" class="address" :title="state.url">{{ state.url || 'Obrint el portal…' }}</p>
    <p role="status" aria-live="polite">{{ loading || state?.loading ? 'Carregant…' : state?.title || '' }}</p>
    <p v-if="state?.loginMessage" role="status" :class="{ 'notice notice-gold': state.login === 'error' }">{{ state.loginMessage }}</p>
    <div v-if="error || state?.error" class="notice notice-error" role="alert">{{ error || state?.error }} <button class="btn btn-secondary" @click="start">Tornar-ho a provar</button></div>
    <section v-if="!loading && settings && !settings.access_url" class="card message"><h2>Configura l'accés a Esfer@</h2><p>{{ auth.isAdmin.value ? 'Indica la URL del portal a Configuració → General → Esfer@.' : 'Demana a l’administrador que indiqui la URL d’accés.' }}</p></section>
    <section v-else-if="!loading && !browser" class="card message"><h2>Navegador no disponible</h2><p>Cal una versió de Cosecre d’escriptori que inclogui el navegador integrat.</p></section>
    <Teleport to="body">
      <div v-if="personalOpen" class="overlay" @click.self="personalOpen = false" @keydown.esc="personalOpen = false">
        <section class="dialog personal-dialog" role="dialog" aria-modal="true" aria-labelledby="sfera-personal-heading">
          <header class="page-head"><h2 id="sfera-personal-heading">Accés personal</h2><button class="btn btn-ghost" @click="personalOpen = false">Tancar</button></header>
          <CredentialsPanel />
        </section>
      </div>
    </Teleport>
    <div ref="surface" class="browser-surface" :class="{ inactive: !state }" aria-label="Contingut del navegador d’Esfer@"></div>
    <p class="text-muted">Pots iniciar sessió manualment o utilitzar el teu accés personal desat. Selecciona un centre i obre «Resum i dades» per consultar pressupostos, proveïdors i factures.</p>
  </div>
</template>
<style scoped>
.sfera { display: grid; gap: 12px; }
.toolbar { display: flex; flex-wrap: wrap; gap: 8px; }
.address { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-size: var(--text-sm); color: var(--ink-500); }
.browser-surface { height: max(360px, calc(100vh - 320px)); border: 1px solid var(--line); border-radius: var(--r-md); background: var(--surface-0); }
.browser-surface.inactive { height: 0; min-height: 0; border: 0; }
.personal-dialog { max-width: 680px; max-height: 90vh; overflow-y: auto; }
.message { padding: 24px; display: grid; gap: 12px; }
</style>
