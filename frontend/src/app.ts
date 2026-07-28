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
import { PLATFORM_KEY, type PlatformIntegration } from './platform'
import { createAppRouter } from './router'
import './style.css'

export type { TokenStorage } from './api/client'
export type { PlatformIntegration } from './platform'

export interface CosecreAppOptions {
  apiBaseUrl?: string
  storage?: TokenStorage
  history?: 'web' | 'hash'
  /** Identifies this app on the session list the hub keeps. */
  client?: string
  clientLabel?: string
  platform?: PlatformIntegration
  settingsPanel?: Component
}

export function createCosecreApp(options: CosecreAppOptions = {}): VueApp<Element> {
  const platform: PlatformIntegration = options.platform ?? { name: 'web' }
  if (options.settingsPanel) {
    platform.settingsPanel = options.settingsPanel
  }

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
