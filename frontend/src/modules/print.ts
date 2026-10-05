/**
 * The print tool — Eines → Impressió.
 *
 * Formerly the standalone Cosecre-print app. Its engine runs in the desktop
 * main process (`desktop/src/main/print/`); this module is its UI, reached
 * through `PlatformIntegration.print`. A browser has no such bridge, and the
 * view explains where to get one.
 */
import type { CosecreModule } from './types'

export const printModule: CosecreModule = {
  id: 'print',
  routes: [
    // Lazy: the desktop half of the view pulls in pdf.js.
    { path: 'eines/impressio', name: 'print', component: () => import('../views/PrintView.vue') },
  ],
  // Shared with documents, which declares it too; declaring it here keeps the
  // module whole on its own.
  navGroups: [{ id: 'eines', label: 'Eines' }],
  nav: [{ name: 'print', label: 'Impressió', icon: 'printer', group: 'eines' }],
}
