/**
 * Requests to the office — the one app every role has.
 *
 * Registered after documents: for the office, documents claims home first and
 * this sits in its Tasques group; a Professor/a has no documents module, so
 * this is where they land.
 */
import { useAuth } from '../composables/useAuth'
import RequestsView from '../views/RequestsView.vue'
import type { CosecreModule } from './types'

export const requestsModule: CosecreModule = {
  id: 'requests',
  routes: [{ path: 'sollicituds', name: 'requests', component: RequestsView }],
  navGroups: [{ id: 'tasques', label: 'Tasques' }],
  nav: [
    { name: 'requests', label: 'Sol·licituds', icon: 'inbox', group: 'tasques', roles: ['admin', 'secretaria'] },
    { name: 'requests', label: 'Sol·licituds', icon: 'inbox', roles: ['professor'] },
  ],
  home: () => (useAuth().isProfessor.value ? { name: 'requests' } : null),
}
