/**
 * The Assistent (beta) — a chat over the hub's data, for the office.
 * Claims no home; it sits at the top of the sidebar, under Estat.
 */
import AssistantView from '../views/AssistantView.vue'
import type { CosecreModule } from './types'

export const assistantModule: CosecreModule = {
  id: 'assistant',
  roles: ['admin', 'secretaria'],
  routes: [{ path: 'assistent', name: 'assistant', component: AssistantView }],
  nav: [{ name: 'assistant', label: 'Assistent', icon: 'sparkles', badge: 'beta' }],
}
