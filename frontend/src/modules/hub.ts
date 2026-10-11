/**
 * The hub's own screens — the account page everyone has, and the admin's
 * settings. Not an app of their own, so no home claim: a role always gets its
 * home from a module made for it, and `account` is only the last resort.
 */
import AccountView from '../views/AccountView.vue'
import SettingsView from '../views/SettingsView.vue'
import type { CosecreModule } from './types'

export const hubModule: CosecreModule = {
  id: 'hub',
  routes: [
    { path: 'account', name: 'account', component: AccountView },
    { path: 'settings', name: 'settings', component: SettingsView, meta: { requiresAdmin: true } },
  ],
  nav: [{ name: 'settings', label: 'Configuració', icon: 'sliders', adminOnly: true, placement: 'foot' }],
}
