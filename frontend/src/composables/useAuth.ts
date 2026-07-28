import { computed, reactive } from 'vue'

import { api, ApiError, clearTokens } from '../api/client'
import type { HubMeta, User } from '../api/types'

const state = reactive<{
  ready: boolean
  loading: boolean
  user: User | null
  error: string | null
  /** Null until the hub has answered, or if it could not be reached. */
  hub: HubMeta | null
  hubError: string | null
}>({
  ready: false,
  loading: false,
  user: null,
  error: null,
  hub: null,
  hubError: null,
})

let bootstrapPromise: Promise<void> | null = null

/**
 * Work out, once per load, who is signed in and what the hub can do.
 *
 * Every route guard awaits this, so it has to be idempotent *and* concurrency
 * safe — hence the shared promise rather than a plain flag.
 */
async function bootstrap() {
  if (state.ready) {
    return
  }
  if (bootstrapPromise) {
    return bootstrapPromise
  }

  bootstrapPromise = (async () => {
    state.loading = true
    // The hub description is unauthenticated and drives the sign-in screen, so
    // it is fetched even when there is no stored session.
    const metaRequest = api
      .meta()
      .then((meta) => {
        state.hub = meta
        state.hubError = null
      })
      .catch((error: unknown) => {
        state.hub = null
        state.hubError = error instanceof ApiError ? error.message : 'The hub is unreachable.'
      })

    try {
      if (!api.hasStoredSession()) {
        state.user = null
        return
      }
      await api.refreshIfNeeded()
      state.user = await api.me()
    } catch {
      clearTokens()
      state.user = null
    } finally {
      await metaRequest
      state.ready = true
      state.loading = false
      bootstrapPromise = null
    }
  })()

  return bootstrapPromise
}

async function authenticate(
  mode: 'login' | 'register',
  payload: { email: string; password: string },
) {
  state.loading = true
  state.error = null
  try {
    const result = mode === 'login' ? await api.login(payload) : await api.register(payload)
    state.user = result.user
    state.ready = true
    // Registering the first account flips `accepts_registration`.
    void api
      .meta()
      .then((meta) => {
        state.hub = meta
      })
      .catch(() => undefined)
    return result.user
  } catch (error) {
    state.error = error instanceof ApiError ? error.message : 'Unexpected authentication error.'
    throw error
  } finally {
    state.loading = false
  }
}

async function logout() {
  state.user = null
  state.error = null
  // Tokens are dropped locally before the call returns, so a hub that is down
  // cannot keep someone signed in.
  await api.logout()
}

export function useAuth() {
  return {
    state,
    user: computed(() => state.user),
    hub: computed(() => state.hub),
    isAuthenticated: computed(() => Boolean(state.user)),
    isAdmin: computed(() => Boolean(state.user?.is_admin)),
    canRegister: computed(() => state.hub?.accepts_registration ?? false),
    bootstrap,
    authenticate,
    logout,
  }
}
