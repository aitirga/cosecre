/**
 * AIM — Artificial Intelligence and Mathematics.
 *
 * The module's whole contract with the shell is this file. Nothing outside
 * `modules/aim/` imports from inside it, and AIM borrows only transport
 * (`api/client`), session (`composables/useAuth`) and two shared components —
 * which is what keeps `createCosecreApp({ modules: [aimModule] })` a viable
 * standalone build rather than an aspiration.
 */
import type { CosecreModule } from '../types'
import { useAimMembership } from './composables/useAimMembership'
import { CA } from './strings'
import AimRosterView from './views/AimRosterView.vue'
import AimStudentView from './views/AimStudentView.vue'

/** The student surface, which has no hub sidebar. */
const TUTOR_ROUTE = { name: 'aim-tutor' } as const

/** Route names that belong to the teacher side of AIM. */
const TEACHER_ROUTES = new Set(['aim-roster'])

export const aimModule: CosecreModule = {
  id: 'aim',
  appSlug: 'cosecre-aim',

  routes: [{ path: 'aim/alumnat', name: 'aim-roster', component: AimRosterView }],

  // Outside `AppShell`, so it must ask for authentication itself — the shell's
  // parent route is what supplies that to everything else.
  rootRoutes: [
    {
      path: '/aim/tutor',
      name: 'aim-tutor',
      component: AimStudentView,
      meta: { requiresAuth: true },
    },
  ],

  nav: [
    {
      name: 'aim-roster',
      label: CA.nav.roster,
      icon: 'users',
      visible: () => useAimMembership().isTeacher.value,
    },
  ],

  enabled: (hub) => hub?.capabilities.aim ?? false,

  bootstrap: () => useAimMembership().bootstrap(),

  /**
   * A student's claim on home.
   *
   * Only a student claims it, and only once membership has resolved — a
   * teacher belongs on the hub's own home like anyone else. Returning null
   * before `ready` matters: an unresolved module must not answer, or the first
   * navigation of a page load would send everyone to the tutor.
   */
  home: () => {
    const aim = useAimMembership()
    return aim.state.ready && aim.isStudent.value ? TUTOR_ROUTE : null
  },

  guard: (to) => {
    const aim = useAimMembership()
    if (!aim.state.ready) return null

    // Teacher screens are teacher-only. The hub enforces this too; this is so
    // the student sees their own page instead of a 403 rendered as an empty table.
    if (TEACHER_ROUTES.has(to.name as string) && !aim.isTeacher.value) {
      return aim.isStudent.value ? TUTOR_ROUTE : { name: 'account' }
    }

    // A student who lands anywhere else in the hub is sent back to their tutor:
    // the shell's index redirect resolves before membership is known, so this
    // is where that first guess gets corrected.
    if (aim.isStudent.value && !String(to.name ?? '').startsWith('aim-') && to.name !== 'account') {
      return TUTOR_ROUTE
    }

    if (!aim.isStudent.value && to.name === 'aim-tutor') {
      return { name: 'account' }
    }

    return null
  },
}
