import { createRouter, createWebHashHistory, createWebHistory, type Router } from 'vue-router'

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
      ...routes.root,
      {
        path: '/',
        component: AppShell,
        meta: { requiresAuth: true },
        children: [{ path: '', redirect: () => homeRoute.value }, ...routes.shell],
      },
      // Anything unrecognised belongs on the default page rather than a blank
      // router view — a stale desktop deep link should not dead-end.
      { path: '/:pathMatch(.*)*', redirect: () => homeRoute.value },
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

    if (to.name === 'login' && auth.isAuthenticated.value) {
      return homeRoute.value
    }

    return moduleGuard(to) ?? true
  })

  return router
}

export default createAppRouter
