/**
 * Whether the signed-in person is in AIM, and as what.
 *
 * Module-scoped reactive state, the same shape as `useAuth`, because the router
 * factory and the nav both read it before any AIM component exists.
 */
import { computed, reactive } from 'vue'

import { ApiError } from '../../../api/client'
import { useAuth } from '../../../composables/useAuth'
import { aimApi } from '../api'
import type { AimIdentity } from '../types'

const state = reactive<{
  ready: boolean
  identity: AimIdentity | null
  /**
   * Which user the identity was resolved for.
   *
   * The registry calls `bootstrap` on every navigation and `useAuth.bootstrap`
   * settles once per load, so a plain `ready` flag would leave a teacher who
   * just signed in with the membership of the anonymous visitor they were a
   * moment ago. Keying on the user id re-resolves on sign-in and clears on
   * sign-out, which a flag cannot do.
   */
  resolvedFor: number | null
}>({
  ready: false,
  identity: null,
  resolvedFor: null,
})

/**
 * One in-flight resolution, shared by concurrent callers.
 *
 * Cleared after awaiting, and only if it is still ours — *not* from a `finally`
 * inside the task. The signed-out path has nothing to fetch and so runs to
 * completion synchronously, which means such a `finally` fires before the
 * assignment that stores the promise: the variable would end up holding an
 * already-resolved promise instead of null, and the next caller would take it
 * and continue with membership that had never been fetched.
 */
let inFlight: Promise<void> | null = null

async function bootstrap() {
  const auth = useAuth()
  const userId = auth.user.value?.id ?? null

  if (state.ready && state.resolvedFor === userId) return
  if (inFlight) return inFlight

  const pending = (async () => {
    try {
      state.identity = userId === null ? null : await aimApi.identity()
      state.resolvedFor = userId
      state.ready = true
    } catch (error) {
      // A hub that cannot answer is treated as one without AIM, so the module
      // hides rather than showing navigation that 403s on click. An unreachable
      // hub is not an answer, so `ready` stays false and the next navigation
      // asks again.
      state.identity = null
      state.resolvedFor = userId
      state.ready = !(error instanceof ApiError && error.status === 0)
    }
  })()

  inFlight = pending
  try {
    await pending
  } finally {
    if (inFlight === pending) inFlight = null
  }
}

export function useAimMembership() {
  return {
    state,
    identity: computed(() => state.identity),
    role: computed(() => state.identity?.role ?? null),
    isMember: computed(() => state.identity?.role != null),
    isTeacher: computed(() => state.identity?.role === 'teacher'),
    isStudent: computed(() => state.identity?.role === 'student'),
    bootstrap,
  }
}
