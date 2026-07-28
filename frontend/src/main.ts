/**
 * Browser entry point.
 *
 * The web app is served from the same origin as its hub, so it needs no
 * configuration: `/api/v1` is proxied in development and same-origin in
 * production. The desktop app builds the same app with its own options.
 */
import { createCosecreApp } from './app'

createCosecreApp({ client: 'web' }).mount('#app')
