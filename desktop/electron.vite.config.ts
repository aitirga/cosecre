import { resolve } from 'node:path'
import vue from '@vitejs/plugin-vue'
import { defineConfig, externalizeDepsPlugin } from 'electron-vite'

/**
 * The renderer builds the *web app's* source, aliased in as `@web`.
 *
 * Importing the sources rather than a built bundle is deliberate: there is one
 * copy of the UI, and a change to it lands in both clients without a publish
 * step in between. `../frontend` is a workspace, so Vue and its friends resolve
 * to the single hoisted copy at the repository root.
 */
const WEB_SRC = resolve('../frontend/src')

/**
 * The print tool's contract lives with the web app that renders it; the main
 * process and the preload import the same file as `@print/contract`.
 */
const PRINT_SRC = resolve('../frontend/src/print')

export default defineConfig({
  main: {
    plugins: [externalizeDepsPlugin()],
    resolve: {
      alias: { '@shared': resolve('src/shared'), '@print': PRINT_SRC },
    },
  },
  preload: {
    plugins: [externalizeDepsPlugin()],
    resolve: {
      alias: { '@shared': resolve('src/shared'), '@print': PRINT_SRC },
    },
  },
  renderer: {
    root: 'src/renderer',
    build: {
      rollupOptions: {
        input: resolve('src/renderer/index.html'),
      },
    },
    resolve: {
      alias: {
        '@web': WEB_SRC,
        '@shared': resolve('src/shared'),
        '@print': PRINT_SRC,
        '@': resolve('src/renderer/src'),
      },
    },
    server: {
      fs: {
        // The dev server has to be allowed to read outside its root, or every
        // `@web/...` import 403s.
        allow: [resolve('.'), WEB_SRC],
      },
    },
    plugins: [vue()],
  },
})
