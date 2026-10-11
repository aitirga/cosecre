/**
 * The teacher's corner: a home that leads to the two things a Professor/a
 * comes for, and the invoices they sent in. Requests live in their own module,
 * shared with the office; their nav entry is declared here so a teacher's
 * sidebar reads in the order they use it.
 */
import MyInvoicesView from '../views/MyInvoicesView.vue'
import TeacherHomeView from '../views/TeacherHomeView.vue'
import type { CosecreModule } from './types'

export const teacherModule: CosecreModule = {
  id: 'teacher',
  roles: ['professor'],
  routes: [
    { path: 'inici', name: 'teacher-home', component: TeacherHomeView },
    { path: 'factures', name: 'my-invoices', component: MyInvoicesView },
  ],
  nav: [
    { name: 'teacher-home', label: 'Inici', icon: 'home' },
    { name: 'requests', label: 'Sol·licituds', icon: 'inbox' },
    { name: 'my-invoices', label: 'Les meves factures', icon: 'invoice' },
  ],
  home: () => ({ name: 'teacher-home' }),
}
