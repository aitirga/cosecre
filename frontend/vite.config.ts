import { fileURLToPath, URL } from 'node:url'

import { VitePWA } from 'vite-plugin-pwa'
import { defineConfig, loadEnv } from 'vite'
import vue from '@vitejs/plugin-vue'

const frontendRoot = fileURLToPath(new URL('.', import.meta.url))

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, frontendRoot, '')
  const frontendHost = env.COSECRE_FRONTEND_HOST || '0.0.0.0'
  const frontendPort = Number(env.COSECRE_FRONTEND_PORT || '5173')
  // COSECRE_BACKEND_URL is the previous name, still honoured so an existing
  // .env keeps working after the rename to the hub.
  const hubUrl = env.COSECRE_HUB_URL || env.COSECRE_BACKEND_URL || 'http://127.0.0.1:8000'

  // Proxying `/api` covers `/api/v1/**`, so the browser talks to one origin and
  // there is no CORS in development.
  const apiProxy = {
    '/api': {
      target: hubUrl,
      changeOrigin: true,
    },
  }

  return {
    plugins: [
      vue(),
      VitePWA({
        registerType: 'autoUpdate',
        workbox: {
          // Serve the cached shell immediately, even while Fly is waking up.
          // Never serve or cache private API responses as navigation pages.
          navigateFallback: '/index.html',
          navigateFallbackDenylist: [/^\/api(?:\/|$)/, /^\/healthz$/],
          globPatterns: ['**/*.{js,css,html,svg,woff2}'],
          // The print tool's desktop half carries pdf.js and only ever runs in
          // the desktop app; a browser should not download it ahead of time.
          globIgnores: ['**/PrintWorkbench-*', '**/pdf.worker*'],
        },
        includeAssets: ['favicon.svg'],
        manifest: {
          name: 'Cosecre',
          short_name: 'Cosecre',
          description: 'Registre de documents comptables.',
          // Matches --accent-600 and --surface-1 in style.css, so the splash and
          // the address bar do not flash a colour the app never uses.
          theme_color: '#3f6fce',
          background_color: '#f5f9fe',
          display: 'standalone',
          start_url: '/',
          icons: [
            {
              src: '/favicon.svg',
              sizes: '512x512',
              type: 'image/svg+xml',
              purpose: 'any',
            },
          ],
        },
      }),
    ],
    server: {
      host: frontendHost,
      port: frontendPort,
      strictPort: true,
      allowedHosts: true,
      proxy: apiProxy,
    },
    preview: {
      host: frontendHost,
      port: frontendPort,
      strictPort: true,
      proxy: apiProxy,
    },
  }
})
