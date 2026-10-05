/**
 * The shared Cosecre client.
 *
 * Both shells build the app from here: `main.ts` for the browser, and the
 * Electron renderer for the desktop. Everything that differs between them —
 * where the hub is, where tokens live, how routing works — arrives as options,
 * so there is exactly one copy of the UI.
 */
import { QueryClient, VueQueryPlugin } from '@tanstack/vue-query'
import { createApp, type App as VueApp, type Component } from 'vue'

import { configureApi, type TokenStorage } from './api/client'
import App from './App.vue'
import { documentsModule } from './modules/documents'
import { printModule } from './modules/print'
import { registerModules } from './modules/registry'
import type { CosecreModule } from './modules/types'
import { PLATFORM_KEY, type PlatformIntegration } from './platform'
import { createAppRouter } from './router'
import './style.css'

export type { TokenStorage } from './api/client'
export type { CosecreModule } from './modules/types'
export type { PlatformIntegration } from './platform'

/**
 * Specific modules first, general last.
 *
 * The first module to claim "home" wins, and documents claims it for everyone,
 * so a module with a narrower claim has to be asked before it. A shell that
 * wants a different set passes `modules:` and gets exactly those.
 *
 * Print claims no home, so it only has to come after documents for the
 * sidebar: its entry joins the Eines group documents opens.
 */
const DEFAULT_MODULES: CosecreModule[] = [documentsModule, printModule]

export interface CosecreAppOptions {
  apiBaseUrl?: string
  storage?: TokenStorage
  history?: 'web' | 'hash'
  /** Identifies this app on the session list the hub keeps. */
  client?: string
  clientLabel?: string
  platform?: PlatformIntegration
  settingsPanel?: Component
  /** Which apps this shell hosts. Order matters — see `DEFAULT_MODULES`. */
  modules?: CosecreModule[]
}

export function createCosecreApp(options: CosecreAppOptions = {}): VueApp<Element> {
  const platform: PlatformIntegration = options.platform ?? { name: 'web' }
  if (options.settingsPanel) {
    platform.settingsPanel = options.settingsPanel
  }

  // Before the router: it reads the registry to build its route table.
  registerModules(options.modules ?? DEFAULT_MODULES)

  configureApi({
    baseUrl: options.apiBaseUrl,
    storage: options.storage,
    client: options.client ?? platform.name,
    clientLabel: options.clientLabel,
  })

  const router = createAppRouter({
    history: options.history,
    withHubPicker: typeof platform.changeHub === 'function',
  })

  const app = createApp(App)
  app.provide(PLATFORM_KEY, platform)
  app.use(router)
  app.use(VueQueryPlugin, {
    queryClient: new QueryClient({
      defaultOptions: {
        queries: {
          // The hub is the source of truth and several people share a
          // workspace, so a stale cache is worse than an extra request.
          refetchOnWindowFocus: true,
          retry: 1,
        },
      },
    }),
  })

  return app
}
