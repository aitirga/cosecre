/**
 * Browser entry point.
 *
 * No configuration by default: the client asks for `/api/v1` relative to
 * whatever origin served it. In development Vite proxies that to the hub; in
 * production, put the two behind one reverse proxy, or point the build at a
 * different hub with `VITE_API_BASE_URL`.
 *
 * The desktop app builds this same app with its own options — see
 * `desktop/src/renderer/src/main.ts`.
 */
import { createCosecreApp } from './app'

createCosecreApp({ client: 'web' }).mount('#app')
