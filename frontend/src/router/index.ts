import { createRouter, createWebHistory } from 'vue-router'

import AppShell from '../components/AppShell.vue'
import { useAuth } from '../composables/useAuth'
import InboxView from '../views/InboxView.vue'
import InvoiceDetailView from '../views/InvoiceDetailView.vue'
import LoginView from '../views/LoginView.vue'
import SettingsView from '../views/SettingsView.vue'

const router = createRouter({
  history: createWebHistory(),
  routes: [
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
        {
          path: '',
          name: 'inbox',
          component: InboxView,
        },
        {
          path: 'invoice/:internalDocNumber',
          name: 'invoice',
          component: InvoiceDetailView,
        },
        {
          path: 'settings',
          name: 'settings',
          component: SettingsView,
          meta: { requiresAdmin: true },
        },
      ],
    },
  ],
})

router.beforeEach(async (to) => {
  const auth = useAuth()
  await auth.bootstrap()

  if (to.meta.requiresAuth && !auth.isAuthenticated.value) {
    return { name: 'login' }
  }

  if (to.meta.requiresAdmin && !auth.isAdmin.value) {
    return { name: 'inbox' }
  }

  if (to.name === 'login' && auth.isAuthenticated.value) {
    return { name: 'inbox' }
  }

  return true
})

export default router
