import { createRouter, createWebHashHistory, createWebHistory, type Router } from 'vue-router'

import AppShell from '../components/AppShell.vue'
import { useAuth } from '../composables/useAuth'
import AccountView from '../views/AccountView.vue'
import ConnectHubView from '../views/ConnectHubView.vue'
import InboxView from '../views/InboxView.vue'
import InvoiceDetailView from '../views/InvoiceDetailView.vue'
import LoginView from '../views/LoginView.vue'
import SettingsView from '../views/SettingsView.vue'

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

  const router = createRouter({
    history: options.history === 'hash' ? createWebHashHistory() : createWebHistory(),
    routes: [
      ...(withHubPicker
        ? [{ path: '/connect', name: 'connect', component: ConnectHubView }]
        : []),
      {
        path: '/login',
        name: 'login',
        component: LoginView,
      },
      {
        path: '/',
        component: AppShell,
        meta: { requiresAuth: true },
        children: [
          { path: '', redirect: { name: 'invoices' } },
          {
            path: 'invoices',
            name: 'invoices',
            component: InboxView,
            meta: { documentType: 'invoice' },
          },
          {
            path: 'tickets',
            name: 'tickets',
            component: InboxView,
            meta: { documentType: 'ticket' },
          },
          {
            path: 'invoices/:internalDocNumber',
            name: 'invoice',
            component: InvoiceDetailView,
            meta: { documentType: 'invoice' },
          },
          {
            path: 'tickets/:internalDocNumber',
            name: 'ticket',
            component: InvoiceDetailView,
            meta: { documentType: 'ticket' },
          },
          { path: 'account', name: 'account', component: AccountView },
          {
            path: 'settings',
            name: 'settings',
            component: SettingsView,
            meta: { requiresAdmin: true },
          },
        ],
      },
      // Anything unrecognised belongs on the default page rather than a blank
      // router view — a stale desktop deep link should not dead-end.
      { path: '/:pathMatch(.*)*', redirect: { name: 'invoices' } },
    ],
  })

  router.beforeEach(async (to) => {
    const auth = useAuth()
    await auth.bootstrap()

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
      return { name: 'invoices' }
    }

    if (to.name === 'login' && auth.isAuthenticated.value) {
      return { name: 'invoices' }
    }

    return true
  })

  return router
}

export default createAppRouter
