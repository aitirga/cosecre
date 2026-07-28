/**
 * The documents module — invoices and tickets.
 *
 * Moved out of `router/index.ts` and `AppShell.vue` unchanged. The two routes
 * per document type sharing one component, with the type carried in `meta`, is
 * the original arrangement; `document-config.ts` still supplies the copy.
 */
import AccountView from '../views/AccountView.vue'
import InboxView from '../views/InboxView.vue'
import InvoiceDetailView from '../views/InvoiceDetailView.vue'
import SettingsView from '../views/SettingsView.vue'
import type { CosecreModule } from './types'

export const documentsModule: CosecreModule = {
  id: 'documents',
  appSlug: 'cosecre-docs',
  routes: [
    { path: 'invoices', name: 'invoices', component: InboxView, meta: { documentType: 'invoice' } },
    { path: 'tickets', name: 'tickets', component: InboxView, meta: { documentType: 'ticket' } },
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
    // Account and Settings are the hub's own screens rather than this module's,
    // but they have nowhere else to live until a second module needs them.
    { path: 'account', name: 'account', component: AccountView },
    { path: 'settings', name: 'settings', component: SettingsView, meta: { requiresAdmin: true } },
  ],
  nav: [
    { name: 'invoices', label: 'Invoices', icon: 'invoice', childRoutes: ['invoice'] },
    { name: 'tickets', label: 'Tickets', icon: 'ticket', childRoutes: ['ticket'] },
    { name: 'settings', label: 'Settings', icon: 'sliders', adminOnly: true },
  ],
  // Registered last, so its unconditional claim on home is the default rather
  // than an override of a module with a better reason to be there.
  home: () => ({ name: 'invoices' }),
}
