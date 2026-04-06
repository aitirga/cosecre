<script setup lang="ts">
import { computed, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'

import { useAuth } from '../composables/useAuth'

const router = useRouter()
const auth = useAuth()

const mode = ref<'login' | 'register'>('register')
const form = reactive({
  email: '',
  password: '',
})

const title = computed(() =>
  mode.value === 'register' ? 'Create the first workspace account.' : 'Sign back into Cosecre.',
)

async function submit() {
  await auth.authenticate(mode.value, form)
  router.push({ name: 'inbox' })
}
</script>

<template>
  <main class="login-page">
    <section class="login-card">
      <div class="copy">
        <p class="eyebrow">Invoice extraction MVP</p>
        <div class="title-wrap">
          <h1 class="title-sizer" aria-hidden="true">Create the first workspace account.</h1>
          <h1 class="title-actual">{{ title }}</h1>
        </div>
        <p>
          The first registered user becomes the admin and configures the shared Google Sheet. After
          that, the same account can sign in from multiple devices.
        </p>
      </div>

      <form class="form-card" @submit.prevent="submit">
        <div class="mode-switch">
          <button type="button" :class="{ active: mode === 'register' }" @click="mode = 'register'">
            Register
          </button>
          <button type="button" :class="{ active: mode === 'login' }" @click="mode = 'login'">
            Login
          </button>
        </div>

        <label>
          <span>Email</span>
          <input v-model="form.email" type="email" placeholder="you@company.com" required />
        </label>

        <label>
          <span>Password</span>
          <input v-model="form.password" type="password" minlength="8" required />
        </label>

        <button class="submit" type="submit" :disabled="auth.state.loading">
          {{ auth.state.loading ? 'Working...' : mode === 'register' ? 'Create Account' : 'Login' }}
        </button>

        <p v-if="auth.state.error" class="error">{{ auth.state.error }}</p>
      </form>
    </section>
  </main>
</template>

<style scoped>
.login-page {
  min-height: 100vh;
  display: grid;
  place-items: center;
  padding: 24px;
}

.login-card {
  width: min(1100px, 100%);
  display: grid;
  grid-template-columns: 1.3fr 1fr;
  gap: 18px;
}

.copy,
.form-card {
  padding: 28px;
  border-radius: 28px;
  box-shadow: var(--shadow);
}

.copy {
  background:
    radial-gradient(circle at top right, rgba(255, 205, 101, 0.34), transparent 25%),
    linear-gradient(160deg, #1f3727 0%, #38563c 100%);
  color: #fffaf2;
  display: grid;
  align-content: space-between;
  gap: 16px;
}

.title-wrap {
  position: relative;
}

.title-sizer {
  visibility: hidden;
  font-size: clamp(3rem, 5vw, 5.5rem);
  max-width: 8ch;
}

.title-actual {
  position: absolute;
  inset: 0;
  font-size: clamp(3rem, 5vw, 5.5rem);
  max-width: 8ch;
}

.form-card {
  background: rgba(255, 250, 242, 0.92);
  display: grid;
  gap: 18px;
}

.mode-switch {
  display: inline-grid;
  grid-template-columns: repeat(2, 1fr);
  padding: 0.3rem;
  border-radius: 999px;
  background: rgba(31, 55, 39, 0.08);
}

.mode-switch button {
  border: 0;
  border-radius: 999px;
  padding: 0.8rem 1rem;
  background: transparent;
}

.mode-switch .active {
  background: white;
  box-shadow: 0 8px 18px rgba(31, 55, 39, 0.08);
}

label {
  display: grid;
  gap: 8px;
}

input {
  border: 1px solid var(--line);
  border-radius: 18px;
  padding: 0.95rem 1rem;
  background: white;
}

.submit {
  border: 0;
  border-radius: 999px;
  background: var(--accent);
  color: white;
  padding: 1rem 1.2rem;
  font-weight: 700;
}

.eyebrow {
  text-transform: uppercase;
  letter-spacing: 0.18em;
  font-size: 0.84rem;
}

.error {
  color: var(--danger);
}

@media (max-width: 880px) {
  .login-card {
    grid-template-columns: 1fr;
  }
}
</style>
