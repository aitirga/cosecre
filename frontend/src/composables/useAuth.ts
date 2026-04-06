import { computed, reactive } from 'vue'

import { api, ApiError, clearTokens } from '../api/client'
import type { User } from '../api/types'

const state = reactive<{
  ready: boolean
  loading: boolean
  user: User | null
  error: string | null
}>({
  ready: false,
  loading: false,
  user: null,
  error: null,
})

let bootstrapPromise: Promise<void> | null = null

async function bootstrap() {
  if (state.ready) {
    return
  }
  if (bootstrapPromise) {
    return bootstrapPromise
  }

  bootstrapPromise = (async () => {
    state.loading = true
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
    return result.user
  } catch (error) {
    state.error = error instanceof ApiError ? error.message : 'Unexpected authentication error.'
    throw error
  } finally {
    state.loading = false
  }
}

function logout() {
  clearTokens()
  state.user = null
}

export function useAuth() {
  return {
    state,
    user: computed(() => state.user),
    isAuthenticated: computed(() => Boolean(state.user)),
    isAdmin: computed(() => Boolean(state.user?.is_admin)),
    bootstrap,
    authenticate,
    logout,
  }
}
