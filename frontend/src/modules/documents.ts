/**
 * The documents module — one accounting register.
 *
 * Invoices and tickets used to be two lists over one component; the models now
 * tell the kinds apart, so there is a single list and a single detail route.
 * Old `/invoices` and `/tickets` links redirect rather than dead-end.
 */
import AccountView from '../views/AccountView.vue'
import DocumentDetailView from '../views/DocumentDetailView.vue'
import RegisterView from '../views/RegisterView.vue'
import SettingsView from '../views/SettingsView.vue'
import type { CosecreModule } from './types'

export const documentsModule: CosecreModule = {
  id: 'documents',
  appSlug: 'cosecre-docs',
  routes: [
    { path: 'registre', name: 'register', component: RegisterView },
    { path: 'registre/:internalDocNumber', name: 'document', component: DocumentDetailView },
    { path: 'invoices/:internalDocNumber?', redirect: (to) => legacyRedirect(to.params) },
    { path: 'tickets/:internalDocNumber?', redirect: (to) => legacyRedirect(to.params) },
    // Account and Settings are the hub's own screens rather than this module's,
    // but they have nowhere else to live until a second module needs them.
    { path: 'account', name: 'account', component: AccountView },
    { path: 'settings', name: 'settings', component: SettingsView, meta: { requiresAdmin: true } },
  ],
  navGroups: [{ id: 'comptabilitat', label: 'Comptabilitat' }],
  nav: [
    {
      name: 'register',
      label: 'Registre',
      icon: 'invoice',
      childRoutes: ['document'],
      group: 'comptabilitat',
    },
    { name: 'settings', label: 'Configuració', icon: 'sliders', adminOnly: true, placement: 'foot' },
  ],
  // Registered last, so its unconditional claim on home is the default rather
  // than an override of a module with a better reason to be there.
  home: () => ({ name: 'register' }),
}

function legacyRedirect(params: Record<string, string | string[]>) {
  const reference = params.internalDocNumber
  return reference
    ? { name: 'document', params: { internalDocNumber: reference } }
    : { name: 'register' }
}
