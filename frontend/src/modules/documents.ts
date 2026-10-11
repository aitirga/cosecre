/**
 * The documents module — one accounting register.
 *
 * Invoices and tickets used to be two lists over one component; the models now
 * tell the kinds apart, so there is a single list and a single detail route.
 * Old `/invoices` and `/tickets` links redirect rather than dead-end.
 */
import { api } from '../api/client'
import { useAuth } from '../composables/useAuth'
import DossierView from '../views/DossierView.vue'
import DocumentDetailView from '../views/DocumentDetailView.vue'
import ReconcileView from '../views/ReconcileView.vue'
import RegisterView from '../views/RegisterView.vue'
import StatementsView from '../views/StatementsView.vue'
import StatusView from '../views/StatusView.vue'
import type { CosecreModule } from './types'

/**
 * The caixeta is a Google Sheet people edit by hand, and the server sleeps
 * when nobody is around — so it is re-read whenever someone opens the app.
 * Once per page load, fire-and-forget: entering never waits on Google.
 */
let caixetaChecked = false
function checkCaixeta() {
  if (caixetaChecked || !useAuth().isAuthenticated.value) return
  caixetaChecked = true
  void api.syncCaixeta(true).catch(() => {
    caixetaChecked = false
  })
}

export const documentsModule: CosecreModule = {
  id: 'documents',
  appSlug: 'cosecre-docs',
  // The office's: Professor/a sends invoices in through their own screens.
  roles: ['admin', 'secretaria'],
  routes: [
    { path: 'estat', name: 'status', component: StatusView },
    { path: 'registre', name: 'register', component: RegisterView },
    { path: 'registre/:internalDocNumber', name: 'document', component: DocumentDetailView },
    { path: 'extractes', name: 'statements', component: StatementsView },
    { path: 'tasques/justificar-extractes', name: 'reconcile', component: ReconcileView },
    { path: 'eines/dossier-extracte', name: 'statement-dossier', component: DossierView },
    { path: 'invoices/:internalDocNumber?', redirect: (to) => legacyRedirect(to.params) },
    { path: 'tickets/:internalDocNumber?', redirect: (to) => legacyRedirect(to.params) },
  ],
  // The id stays `comptabilitat` so the sidebar remembers whether it was collapsed.
  navGroups: [
    { id: 'comptabilitat', label: 'Bases de dades' },
    { id: 'tasques', label: 'Tasques' },
    { id: 'eines', label: 'Eines' },
  ],
  nav: [
    // Top level, first: the overview everything else is the detail of.
    { name: 'status', label: 'Estat', icon: 'activity' },
    {
      name: 'register',
      label: 'Registre',
      icon: 'invoice',
      childRoutes: ['document'],
      group: 'comptabilitat',
    },
    { name: 'statements', label: 'Extractes', icon: 'bank', group: 'comptabilitat' },
    { name: 'reconcile', label: 'Justificar extractes', icon: 'tasks', group: 'tasques' },
    { name: 'statement-dossier', label: "Dossier d'extracte", icon: 'invoice', group: 'eines' },
  ],
  // Registered last, so its unconditional claim on home is the default rather
  // than an override of a module with a better reason to be there.
  home: () => ({ name: 'register' }),
  bootstrap: async () => checkCaixeta(),
}

function legacyRedirect(params: Record<string, string | string[]>) {
  const reference = params.internalDocNumber
  return reference
    ? { name: 'document', params: { internalDocNumber: reference } }
    : { name: 'register' }
}
