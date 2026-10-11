/**
 * Requests to the office — the one app every role has.
 *
 * For the office it sits in the Tasques group documents opens. A teacher's
 * entry is declared by the teacher module, beside their other screens.
 */
import RequestsView from '../views/RequestsView.vue'
import type { CosecreModule } from './types'

export const requestsModule: CosecreModule = {
  id: 'requests',
  routes: [{ path: 'sollicituds', name: 'requests', component: RequestsView }],
  navGroups: [{ id: 'tasques', label: 'Tasques' }],
  nav: [
    { name: 'requests', label: 'Sol·licituds', icon: 'inbox', group: 'tasques', roles: ['admin', 'secretaria'] },
  ],
}
