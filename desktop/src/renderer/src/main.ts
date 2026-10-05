/**
 * Desktop entry point.
 *
 * Builds the same Vue app the browser runs, with three substitutions: the hub
 * URL comes from the app's own store rather than the page origin, tokens live
 * in the main process rather than `localStorage`, and routing is hash-based
 * because a packaged renderer is loaded from `file://`.
 */
import { createCosecreApp, type TokenStorage } from '@web/app'

import UpdatePanel from './UpdatePanel.vue'
import './desktop.css'

const bridge = window.cosecreDesktop
const { hubUrl, tokens, version, deviceLabel } = bridge.bootstrap

/**
 * A synchronous view over the main process's token store.
 *
 * The snapshot handed over at preload time is the read path; writes update it
 * and are mirrored to disk without blocking. The API client needs `get` to
 * answer immediately, which rules out talking to the main process per call.
 */
const cache: Record<string, string> = { ...tokens }

const storage: TokenStorage = {
  get: (key) => cache[key] ?? null,
  set: (key, value) => {
    cache[key] = value
    bridge.setToken(key, value)
  },
  remove: (key) => {
    delete cache[key]
    bridge.removeToken(key)
  },
}

createCosecreApp({
  // Empty until a hub is chosen; the router sends an unconfigured app to the
  // hub picker rather than a sign-in form that cannot work.
  apiBaseUrl: hubUrl ?? '',
  storage,
  history: 'hash',
  client: 'desktop',
  clientLabel: deviceLabel,
  platform: {
    name: 'desktop',
    version,
    hubUrl: hubUrl ?? undefined,
    // The main process reloads the window once this resolves, so nothing here
    // has to reconcile the old hub's cached state.
    changeHub: (url) => bridge.setHubUrl(url),
    settingsPanel: UpdatePanel,
    print: bridge.print,
  },
}).mount('#app')
