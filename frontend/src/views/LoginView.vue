<script setup lang="ts">
import { computed, reactive, ref, watchEffect } from 'vue'
import { RouterLink, useRouter } from 'vue-router'

import AppIcon from '../components/AppIcon.vue'
import BrandMark from '../components/BrandMark.vue'
import { useAuth } from '../composables/useAuth'
import { usePlatform } from '../platform'

const router = useRouter()
const auth = useAuth()
const platform = usePlatform()

const mode = ref<'login' | 'register'>('login')
const form = reactive({ email: '', password: '' })

/**
 * The hub only accepts registration while it has no accounts, so the very
 * first visit lands on "create the first account" and every later one on
 * sign-in. Nobody has to know which case they are in.
 */
watchEffect(() => {
  if (auth.canRegister.value && !auth.state.hub?.has_users) {
    mode.value = 'register'
  }
})

const isFirstAccount = computed(() => auth.state.hub?.has_users === false)

const heading = computed(() => {
  if (mode.value === 'register') {
    return isFirstAccount.value ? 'Create the first account' : 'Create an account'
  }
  return 'Sign in'
})

const lead = computed(() => {
  if (auth.state.hubError) return auth.state.hubError
  if (mode.value === 'register' && isFirstAccount.value) {
    return 'This hub has no accounts yet. The first one you create becomes the administrator and can add everyone else.'
  }
  if (mode.value === 'register') return 'Register a new account on this hub.'
  return 'Use the account an administrator created for you.'
})

const submitting = computed(() => auth.state.loading)

async function submit() {
  try {
    await auth.authenticate(mode.value, { email: form.email, password: form.password })
    // `/` rather than a named route: the shell's index redirect asks the module
    // registry where this particular person belongs, which is not knowable here
    // — their modules have not resolved their membership yet.
    await router.replace('/')
  } catch {
    // The message is already on auth.state.error.
  }
}
</script>

<template>
  <main class="page">
    <section class="panel">
      <header class="head">
        <BrandMark :size="34" />
        <div>
          <p class="wordmark">Cosecre</p>
          <p class="tagline">Document intake, extraction and review</p>
        </div>
      </header>

      <div class="card form-card">
        <div class="card-body">
          <h1 class="title">{{ heading }}</h1>
          <p class="lead">{{ lead }}</p>

          <div v-if="auth.canRegister.value && !isFirstAccount" class="segmented" role="tablist">
            <button
              type="button"
              role="tab"
              :aria-selected="mode === 'login'"
              :class="{ active: mode === 'login' }"
              @click="mode = 'login'"
            >
              Sign in
            </button>
            <button
              type="button"
              role="tab"
              :aria-selected="mode === 'register'"
              :class="{ active: mode === 'register' }"
              @click="mode = 'register'"
            >
              Register
            </button>
          </div>

          <form class="form" @submit.prevent="submit">
            <label class="field">
              <span class="label">Email</span>
              <input
                v-model="form.email"
                class="input"
                type="email"
                autocomplete="username"
                placeholder="you@company.com"
                required
              />
            </label>

            <label class="field">
              <span class="label">Password</span>
              <input
                v-model="form.password"
                class="input"
                type="password"
                :autocomplete="mode === 'register' ? 'new-password' : 'current-password'"
                :minlength="mode === 'register' ? 8 : undefined"
                required
              />
              <span v-if="mode === 'register'" class="hint">At least 8 characters.</span>
            </label>

            <button class="btn btn-primary btn-lg btn-block" type="submit" :disabled="submitting">
              {{
                submitting
                  ? 'Working…'
                  : mode === 'register'
                    ? 'Create account'
                    : 'Sign in'
              }}
            </button>

            <p v-if="auth.state.error" class="notice notice-error">
              <AppIcon name="alert" :size="15" />
              <span>{{ auth.state.error }}</span>
            </p>
          </form>
        </div>

        <footer class="card-foot">
          <span class="hub-line">
            <AppIcon name="server" :size="13" />
            <span class="truncate">{{ auth.state.hub?.name ?? 'Cosecre Hub' }}</span>
            <span v-if="auth.state.hub" class="muted">v{{ auth.state.hub.version }}</span>
          </span>
          <RouterLink v-if="platform.changeHub" class="btn btn-ghost btn-sm" :to="{ name: 'connect' }">
            Change hub
          </RouterLink>
        </footer>
      </div>
    </section>
  </main>
</template>

<style scoped>
.page {
  min-height: 100vh;
  display: grid;
  place-items: center;
  padding: 24px;
}

.panel {
  width: min(400px, 100%);
  display: grid;
  gap: 18px;
}

.head {
  display: flex;
  align-items: center;
  gap: 11px;
}

.wordmark {
  font-size: var(--text-xl);
  font-weight: 650;
  letter-spacing: -0.02em;
  line-height: 1.1;
}

.tagline {
  font-size: var(--text-sm);
  color: var(--ink-400);
}

.form-card {
  box-shadow: var(--shadow-sm);
}

.title {
  font-size: var(--text-lg);
}

.lead {
  margin-top: 5px;
  font-size: var(--text-base);
  line-height: 1.55;
  color: var(--ink-500);
}

.segmented {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 2px;
  margin-top: 16px;
  padding: 2px;
  border-radius: var(--r-md);
  background: var(--surface-2);
}

.segmented button {
  padding: 5px 10px;
  border: 0;
  border-radius: var(--r-sm);
  background: transparent;
  font-size: var(--text-base);
  font-weight: 500;
  color: var(--ink-500);
}

.segmented button.active {
  background: var(--surface-0);
  color: var(--ink-900);
  box-shadow: var(--shadow-xs);
}

.form {
  display: grid;
  gap: 14px;
  margin-top: 18px;
}

.card-foot {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  padding: 9px 12px;
  border-top: 1px solid var(--line);
  background: var(--surface-1);
  border-radius: 0 0 var(--r-lg) var(--r-lg);
}

.hub-line {
  display: flex;
  align-items: center;
  gap: 6px;
  min-width: 0;
  font-size: var(--text-sm);
  color: var(--ink-500);
}
</style>
