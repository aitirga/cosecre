import { createRouter, createWebHashHistory, createWebHistory, type Router } from 'vue-router'

import type { Role } from '../api/types'
import AppShell from '../components/AppShell.vue'
import { useAuth } from '../composables/useAuth'
import { bootstrapModules, moduleGuard, moduleRoutes, useModules } from '../modules/registry'
import ConnectHubView from '../views/ConnectHubView.vue'
import LoginView from '../views/LoginView.vue'

export interface RouterOptions {
  /**
   * `hash` for the desktop app: a packaged renderer is loaded from `file://`,
   * where a pushState path has no server to resolve it and a reload 404s.
   */
  history?: 'web' | 'hash'
  /** Adds the hub-picker route. Only the desktop shell can act on it. */
  withHubPicker?: boolean
}

/** Stands in for routes the guard always sends somewhere else. */
const Placeholder = { render: () => null }

const RELOAD_KEY = 'cosecre:chunk-reload'

/** The browser's wording varies; these cover Chrome, Firefox and Safari. */
function isChunkLoadError(error: unknown): boolean {
  const message = error instanceof Error ? error.message : String(error)
  return /dynamically imported module|module script failed|Importing a module script failed/i.test(
    message,
  )
}

export function createAppRouter(options: RouterOptions = {}): Router {
  const withHubPicker = options.withHubPicker ?? false
  const { homeRoute } = useModules()
  const routes = moduleRoutes()

  const router = createRouter({
    history: options.history === 'hash' ? createWebHashHistory() : createWebHistory(),
    routes: [
      ...(withHubPicker ? [{ path: '/connect', name: 'connect', component: ConnectHubView }] : []),
      {
        path: '/login',
        name: 'login',
        component: LoginView,
      },
      // Where an invitation link lands. Public: it is how an account first gets in.
      // Same screen as sign-in, opened on the invitation.
      { path: '/activar/:token', name: 'activate', component: LoginView },
      ...routes.root,
      {
        path: '/',
        component: AppShell,
        meta: { requiresAuth: true },
        // Not a `redirect`: those resolve before the guard below has asked who
        // is signed in, and home depends on the role. The guard sends it on.
        children: [{ path: '', name: 'home', component: Placeholder }, ...routes.shell],
      },
      // Anything unrecognised belongs on the default page rather than a blank
      // router view — a stale desktop deep link should not dead-end.
      { path: '/:pathMatch(.*)*', name: 'not-found', component: Placeholder },
    ],
  })

  router.beforeEach(async (to) => {
    const auth = useAuth()
    await auth.bootstrap()
    // Modules resolve their own membership here, so `homeRoute` is already
    // correct on first paint: a student lands in their waiting room instead of
    // flashing a screen they have no business seeing.
    await bootstrapModules()

    if (to.name === 'connect') {
      return true
    }

    // A shell that can change hubs should offer that when the current one is
    // unreachable, instead of showing a sign-in form that cannot work.
    if (withHubPicker && auth.state.hubError) {
      return { name: 'connect' }
    }

    if (to.meta.requiresAuth && !auth.isAuthenticated.value) {
      return { name: 'login' }
    }

    if (to.meta.requiresAdmin && !auth.isAdmin.value) {
      return homeRoute.value
    }

    // A route for other roles sends people home rather than to a 403 page:
    // whatever they typed or bookmarked, home is the right place for them.
    if (to.matched.some((record) => !auth.hasRole(record.meta.roles))) {
      return homeRoute.value
    }

    if ((to.name === 'login' || to.name === 'activate') && auth.isAuthenticated.value) {
      return homeRoute.value
    }

    if (to.name === 'home' || to.name === 'not-found') {
      return auth.isAuthenticated.value ? homeRoute.value : { name: 'login' }
    }

    return moduleGuard(to) ?? true
  })

  // A tab opened before a deploy still asks for the old hash of a lazy route
  // (Eines → Impressió), gets a 404, and the router quietly stays put — a
  // click that does nothing. Load the page fresh at the target instead; the
  // flag stops a chunk that is really broken from reloading forever.
  router.onError((error, to) => {
    if (!isChunkLoadError(error)) return
    const href = router.resolve(to).href
    if (sessionStorage.getItem(RELOAD_KEY) === href) return
    sessionStorage.setItem(RELOAD_KEY, href)
    window.location.assign(href)
  })
  router.afterEach(() => sessionStorage.removeItem(RELOAD_KEY))

  return router
}

declare module 'vue-router' {
  interface RouteMeta {
    requiresAuth?: boolean
    requiresAdmin?: boolean
    /** Who may open the route; stamped from the owning module's `roles`. */
    roles?: readonly Role[]
  }
}

export default createAppRouter
