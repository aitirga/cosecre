<script setup lang="ts">
import { computed, reactive, ref, watch, watchEffect } from 'vue'
import { RouterLink, useRoute, useRouter } from 'vue-router'

import { api, ApiError } from '../api/client'
import type { InvitePreview } from '../api/types'
import AppIcon from '../components/AppIcon.vue'
import BrandMark from '../components/BrandMark.vue'
import RoleBadge from '../components/RoleBadge.vue'
import { useAuth } from '../composables/useAuth'
import { usePlatform } from '../platform'

const route = useRoute()
const router = useRouter()
const auth = useAuth()
const platform = usePlatform()

/**
 * `invite` opens an account with the e-mail and six-digit code an admin handed
 * over; `link` is the same, arrived at through the invitation link, so the
 * hub already knows who it is for.
 */
type Mode = 'login' | 'register' | 'invite' | 'link'
const mode = ref<Mode>('login')
const form = reactive({ email: '', password: '', confirm: '', code: '' })

const inviteToken = computed(() =>
  typeof route.params.token === 'string' ? route.params.token : null,
)
const invite = ref<InvitePreview | null>(null)
const inviteError = ref<string | null>(null)

watch(
  inviteToken,
  async (token) => {
    if (!token) return
    mode.value = 'link'
    invite.value = null
    inviteError.value = null
    try {
      invite.value = await api.invitePreview(token)
      form.email = invite.value.email
    } catch (error) {
      inviteError.value =
        error instanceof ApiError ? error.message : "No s'ha pogut llegir la invitació."
    }
  },
  { immediate: true },
)

/**
 * The hub only accepts registration while it has no accounts, so the very
 * first visit lands on "create the first account" and every later one on
 * sign-in. Nobody has to know which case they are in.
 */
watchEffect(() => {
  if (mode.value === 'login' && auth.canRegister.value && !auth.state.hub?.has_users) {
    mode.value = 'register'
  }
})

const isFirstAccount = computed(() => auth.state.hub?.has_users === false)
const choosingPassword = computed(() => mode.value !== 'login')
const opensInvite = computed(() => mode.value === 'invite' || mode.value === 'link')

const heading = computed(() => {
  if (mode.value === 'link') {
    const name = invite.value?.display_name?.split(' ')[0]
    return name ? `Benvingut/da, ${name}` : 'Activa el teu compte'
  }
  if (mode.value === 'invite') return 'Activa el teu compte'
  if (mode.value === 'register') {
    return isFirstAccount.value ? 'Crea el primer compte' : 'Crea un compte'
  }
  return 'Inicia la sessió'
})

const lead = computed(() => {
  if (auth.state.hubError) return auth.state.hubError
  if (mode.value === 'link') {
    return inviteError.value ?? 'Tria la contrasenya amb què entraràs a partir d\'ara.'
  }
  if (mode.value === 'invite') {
    return 'Escriu el correu i el codi de 6 xifres que t\'ha donat l\'administrador, i tria una contrasenya.'
  }
  if (mode.value === 'register' && isFirstAccount.value) {
    return 'Aquest hub encara no té comptes. El primer que creïs serà l\'administrador i podrà afegir la resta.'
  }
  if (mode.value === 'register') return 'Registra un compte nou en aquest hub.'
  return 'Fes servir el compte que t\'ha creat un administrador.'
})

const submitting = computed(() => auth.state.loading)
const mismatch = computed(
  () => opensInvite.value && form.confirm.length > 0 && form.confirm !== form.password,
)

function switchTo(next: Mode) {
  mode.value = next
  auth.state.error = null
  form.password = ''
  form.confirm = ''
}

async function submit() {
  if (mismatch.value) return
  try {
    if (mode.value === 'link' && inviteToken.value) {
      await auth.activate({ token: inviteToken.value, password: form.password })
    } else if (mode.value === 'invite') {
      await auth.activate({ email: form.email, code: form.code, password: form.password })
    } else {
      await auth.authenticate(mode.value === 'register' ? 'register' : 'login', {
        email: form.email,
        password: form.password,
      })
    }
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
          <p class="tagline">Registre de documents comptables</p>
        </div>
      </header>

      <div class="card form-card">
        <div class="card-body">
          <h1 class="title">{{ heading }}</h1>
          <p class="lead">{{ lead }}</p>

          <p v-if="mode === 'link' && invite" class="invite-for">
            <span class="truncate">{{ invite.email }}</span>
            <RoleBadge :role="invite.role" />
          </p>

          <div
            v-if="auth.canRegister.value && !isFirstAccount && !opensInvite"
            class="segmented"
            role="tablist"
          >
            <button
              type="button"
              role="tab"
              :aria-selected="mode === 'login'"
              :class="{ active: mode === 'login' }"
              @click="switchTo('login')"
            >
              Entra
            </button>
            <button
              type="button"
              role="tab"
              :aria-selected="mode === 'register'"
              :class="{ active: mode === 'register' }"
              @click="switchTo('register')"
            >
              Registra't
            </button>
          </div>

          <form v-if="!(mode === 'link' && !invite)" class="form" @submit.prevent="submit">
            <label v-if="mode !== 'link'" class="field">
              <span class="label">Correu electrònic</span>
              <input
                v-model="form.email"
                class="input"
                type="email"
                autocomplete="username"
                placeholder="nom@centre.cat"
                required
              />
            </label>

            <label v-if="mode === 'invite'" class="field">
              <span class="label">Codi d'invitació</span>
              <input
                v-model="form.code"
                class="input input-mono code-input"
                inputmode="numeric"
                autocomplete="one-time-code"
                pattern="[0-9]{6}"
                maxlength="6"
                placeholder="000000"
                required
              />
            </label>

            <label class="field">
              <span class="label">{{ opensInvite ? 'Nova contrasenya' : 'Contrasenya' }}</span>
              <input
                v-model="form.password"
                class="input"
                type="password"
                :autocomplete="choosingPassword ? 'new-password' : 'current-password'"
                :minlength="choosingPassword ? 8 : undefined"
                required
              />
              <span v-if="choosingPassword" class="hint">Mínim 8 caràcters.</span>
            </label>

            <label v-if="opensInvite" class="field">
              <span class="label">Repeteix-la</span>
              <input
                v-model="form.confirm"
                class="input"
                type="password"
                autocomplete="new-password"
                minlength="8"
                required
              />
              <span v-if="mismatch" class="hint hint-error">No coincideixen.</span>
            </label>

            <button
              class="btn btn-primary btn-lg btn-block"
              type="submit"
              :disabled="submitting || mismatch"
            >
              {{
                submitting
                  ? 'Un moment…'
                  : opensInvite
                    ? 'Activa el compte'
                    : mode === 'register'
                      ? 'Crea el compte'
                      : 'Entra'
              }}
            </button>

            <p v-if="auth.state.error" class="notice notice-error">
              <AppIcon name="alert" :size="15" />
              <span>{{ auth.state.error }}</span>
            </p>
          </form>

          <p v-if="mode === 'login'" class="switch">
            Primer cop?
            <button type="button" class="link-btn" @click="switchTo('invite')">
              Tinc un codi d'invitació
            </button>
          </p>
          <p v-else-if="opensInvite" class="switch">
            <RouterLink v-if="mode === 'link'" class="link-btn" :to="{ name: 'login' }">
              Ja tinc contrasenya
            </RouterLink>
            <button v-else type="button" class="link-btn" @click="switchTo('login')">
              Ja tinc contrasenya
            </button>
          </p>
        </div>

        <footer class="card-foot">
          <span class="hub-line">
            <AppIcon name="server" :size="13" />
            <span class="truncate">{{ auth.state.hub?.name ?? 'Cosecre Hub' }}</span>
            <span v-if="auth.state.hub" class="muted">v{{ auth.state.hub.version }}</span>
          </span>
          <RouterLink v-if="platform.changeHub" class="btn btn-ghost btn-sm" :to="{ name: 'connect' }">
            Canvia de hub
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

.invite-for {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  margin-top: 14px;
  padding: 7px 10px;
  border: 1px solid var(--line);
  border-radius: var(--r-md);
  background: var(--surface-1);
  font-size: var(--text-base);
  color: var(--ink-700);
}

.code-input {
  letter-spacing: 0.3em;
  font-size: var(--text-md);
}

.hint-error {
  color: var(--danger-700);
}

.switch {
  margin-top: 14px;
  font-size: var(--text-sm);
  color: var(--ink-500);
  text-align: center;
}

.link-btn {
  padding: 0;
  border: 0;
  background: none;
  font: inherit;
  font-weight: 600;
  color: var(--accent-700);
  cursor: pointer;
  text-decoration: none;
}

.link-btn:hover {
  text-decoration: underline;
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
