<script setup lang="ts">
import { computed, nextTick, reactive, ref } from 'vue'
import { RouterLink, useRouter } from 'vue-router'
import { useMutation, useQuery } from '@tanstack/vue-query'

import { api, ApiError } from '../api/client'
import type { SessionInfo } from '../api/types'
import AppIcon from '../components/AppIcon.vue'
import RoleBadge from '../components/RoleBadge.vue'
import type { IconName } from '../components/icons'
import { useAuth } from '../composables/useAuth'
import { usePlatform } from '../platform'

const auth = useAuth()
const platform = usePlatform()
const router = useRouter()

const user = computed(() => auth.user.value)

const initials = computed(() => {
  const source = (user.value?.display_name || user.value?.email.split('@')[0] || '?').trim()
  const parts = source.split(/[\s._-]+/).filter(Boolean)
  return ((parts[0]?.[0] ?? '') + (parts[1]?.[0] ?? '')).toUpperCase() || '?'
})

// ── Name ─────────────────────────────────────────────────────────────────────
const editingName = ref(false)
const nameDraft = ref('')
const nameError = ref('')
const nameInput = ref<HTMLInputElement | null>(null)

async function startName() {
  nameDraft.value = user.value?.display_name ?? ''
  nameError.value = ''
  editingName.value = true
  await nextTick()
  nameInput.value?.select()
}

function closeName() {
  editingName.value = false
  nameError.value = ''
}

const saveName = useMutation({
  mutationFn: () => api.updateMe({ display_name: nameDraft.value.trim() || null }),
  onSuccess: (fresh) => {
    auth.setUser(fresh)
    closeName()
  },
  onError: (error) => {
    nameError.value = error instanceof ApiError ? error.message : "No s'ha pogut desar el nom."
  },
})

function submitName() {
  if ((nameDraft.value.trim() || null) === (user.value?.display_name ?? null)) closeName()
  else saveName.mutate()
}

// ── Dates ────────────────────────────────────────────────────────────────────
/** The hub writes UTC without an offset; read bare, it would pass for local time. */
function toDate(iso: string) {
  return new Date(/[zZ]|[+-]\d\d:?\d\d$/.test(iso) ? iso : `${iso}Z`)
}

const relative = new Intl.RelativeTimeFormat('ca', { numeric: 'auto' })
const STEPS: [Intl.RelativeTimeFormatUnit, number][] = [
  ['minute', 60],
  ['hour', 24],
  ['day', 30],
  ['month', 12],
  ['year', Infinity],
]

/** "fa 3 hores", "d'aquí a 5 dies": a session list reads by distance, not by date. */
function fromNow(iso: string) {
  let value = (toDate(iso).getTime() - Date.now()) / 60_000
  if (Math.abs(value) < 1) return 'ara mateix'
  for (const [unit, size] of STEPS) {
    if (Math.abs(value) < size) return relative.format(Math.round(value), unit)
    value /= size
  }
  return ''
}

function longDate(iso: string) {
  return toDate(iso).toLocaleDateString('ca-ES', { day: 'numeric', month: 'long', year: 'numeric' })
}

function fullStamp(iso: string) {
  return toDate(iso).toLocaleString('ca-ES', { dateStyle: 'medium', timeStyle: 'short' })
}

// ── Sessions ─────────────────────────────────────────────────────────────────
const sessionsQuery = useQuery({ queryKey: ['sessions'], queryFn: api.sessions })
const sessions = computed(() => sessionsQuery.data.value ?? [])

function describe(session: SessionInfo): { name: string; icon: IconName } {
  if (session.client === 'desktop') return { name: "Aplicació d'escriptori", icon: 'monitor' }
  if (session.client === 'web') return { name: 'Navegador', icon: 'globe' }
  return { name: session.client ?? 'Client desconegut', icon: 'server' }
}

// Revoking everything is the panic button, so it asks once more in place.
const confirmingLogoutAll = ref(false)

async function leave() {
  await auth.logout()
  await router.push({ name: 'login' })
}

const logoutAll = useMutation({
  mutationFn: api.logoutAll,
  onSettled: leave,
})

// ── Password ─────────────────────────────────────────────────────────────────
const editingPassword = ref(false)
const showPasswords = ref(false)
const passwordForm = reactive({ current: '', next: '', repeat: '' })
const passwordError = ref('')

const longEnough = computed(() => passwordForm.next.length >= 8)
const matches = computed(() => passwordForm.repeat.length > 0 && passwordForm.repeat === passwordForm.next)
const canSubmit = computed(() => Boolean(passwordForm.current) && longEnough.value && matches.value)

function closePassword() {
  editingPassword.value = false
  showPasswords.value = false
  passwordError.value = ''
  Object.assign(passwordForm, { current: '', next: '', repeat: '' })
}

const changePassword = useMutation({
  mutationFn: () =>
    api.changePassword({ current_password: passwordForm.current, new_password: passwordForm.next }),
  // The hub revokes every session on a password change, this one included,
  // so carrying on here would only end in a surprise sign-out later.
  onSuccess: leave,
  onError: (error) => {
    passwordError.value =
      error instanceof ApiError ? error.message : "No s'ha pogut canviar la contrasenya."
  },
})
</script>

<template>
  <div class="account-page">
    <header class="page-head">
      <div>
        <h1 class="page-title">El meu compte</h1>
        <p class="page-lead">El teu perfil, la contrasenya i les aplicacions amb sessió iniciada.</p>
      </div>
    </header>

    <!-- ── Profile ────────────────────────────────────────────────────── -->
    <section class="card">
      <div class="profile">
        <span class="avatar" :class="auth.role.value && `role-${auth.role.value}`" aria-hidden="true">{{ initials }}</span>
        <form v-if="editingName" class="profile-text name-form" @submit.prevent="submitName">
          <div class="name-row">
            <input
              ref="nameInput"
              v-model="nameDraft"
              class="input name-input"
              maxlength="255"
              autocomplete="name"
              placeholder="El teu nom"
              aria-label="Nom"
              @keydown.esc.prevent="closeName"
            />
            <button class="btn btn-ghost btn-sm" type="button" @click="closeName">Cancel·la</button>
            <button class="btn btn-primary btn-sm" type="submit" :disabled="saveName.isPending.value">
              {{ saveName.isPending.value ? 'Desant…' : 'Desa' }}
            </button>
          </div>
          <p v-if="nameError" class="notice notice-error">
            <AppIcon name="alert" :size="15" />
            <span>{{ nameError }}</span>
          </p>
          <p v-else class="muted truncate">{{ user?.email }} · Si el deixes buit es mostra el correu.</p>
        </form>
        <div v-else class="profile-text">
          <div class="name-row">
            <h2 class="profile-name truncate">{{ user?.display_name || user?.email }}</h2>
            <button class="btn btn-ghost btn-icon btn-sm" type="button" title="Canvia el nom" aria-label="Canvia el nom" @click="startName">
              <AppIcon name="pencil" />
            </button>
          </div>
          <p v-if="user?.display_name" class="muted truncate">{{ user?.email }}</p>
        </div>
        <RoleBadge v-if="auth.role.value" :role="auth.role.value" />
      </div>

      <dl class="facts">
        <div class="fact">
          <dt>Membre des de</dt>
          <dd>{{ user ? longDate(user.created_at) : '—' }}</dd>
        </div>
        <div class="fact">
          <dt>Últim accés</dt>
          <dd :title="user?.last_login_at ? fullStamp(user.last_login_at) : undefined">
            {{ user?.last_login_at ? fromNow(user.last_login_at) : 'Mai' }}
          </dd>
        </div>
        <div class="fact">
          <dt>Contrasenya canviada</dt>
          <dd :title="user?.password_set_at ? fullStamp(user.password_set_at) : undefined">
            {{ user?.password_set_at ? fromNow(user.password_set_at) : '—' }}
          </dd>
        </div>
      </dl>

      <p v-if="auth.isAdmin.value" class="profile-foot">
        <AppIcon name="users" :size="14" />
        <span>El rol es canvia des de</span>
        <RouterLink class="link" :to="{ name: 'settings', query: { tab: 'team' } }">Configuració · Equip</RouterLink>
      </p>
      <p v-else class="profile-foot">
        <AppIcon name="users" :size="14" />
        <span>Per canviar el rol, demana-ho al secretari o la secretària.</span>
      </p>
    </section>

    <!-- ── Security ───────────────────────────────────────────────────── -->
    <section class="card">
      <div class="card-head">
        <div>
          <h2 class="card-title">Seguretat</h2>
          <p class="hint">Canviar la contrasenya tanca totes les sessions, aquesta inclosa.</p>
        </div>
      </div>

      <div class="row">
        <div class="row-label">
          <span class="label">Contrasenya</span>
          <span class="hint">
            {{ user?.password_set_at ? `Canviada ${fromNow(user.password_set_at)}.` : 'Mínim 8 caràcters.' }}
          </span>
        </div>
        <div v-if="!editingPassword" class="row-control">
          <span class="dots" aria-hidden="true">••••••••••</span>
          <button class="btn btn-outline btn-sm" type="button" @click="editingPassword = true">
            <AppIcon name="lock" />
            Canvia-la
          </button>
        </div>

        <form v-else class="password" @submit.prevent="canSubmit && changePassword.mutate()">
          <label class="field">
            <span class="sublabel">Contrasenya actual</span>
            <input
              v-model="passwordForm.current"
              class="input"
              :type="showPasswords ? 'text' : 'password'"
              autocomplete="current-password"
              required
            />
          </label>
          <div class="pair">
            <label class="field">
              <span class="sublabel">Contrasenya nova</span>
              <input
                v-model="passwordForm.next"
                class="input"
                :type="showPasswords ? 'text' : 'password'"
                autocomplete="new-password"
                minlength="8"
                required
              />
            </label>
            <label class="field">
              <span class="sublabel">Repeteix-la</span>
              <input
                v-model="passwordForm.repeat"
                class="input"
                :type="showPasswords ? 'text' : 'password'"
                autocomplete="new-password"
                required
              />
            </label>
          </div>

          <ul class="checks">
            <li :class="{ 'is-ok': longEnough }">
              <AppIcon :name="longEnough ? 'check' : 'close'" :size="12" />
              8 caràcters o més
            </li>
            <li :class="{ 'is-ok': matches }">
              <AppIcon :name="matches ? 'check' : 'close'" :size="12" />
              Les dues coincideixen
            </li>
          </ul>

          <p v-if="passwordError" class="notice notice-error">
            <AppIcon name="alert" :size="15" />
            <span>{{ passwordError }}</span>
          </p>

          <div class="password-actions">
            <button class="btn btn-ghost btn-sm" type="button" @click="showPasswords = !showPasswords">
              <AppIcon :name="showPasswords ? 'eye-off' : 'eye'" />
              {{ showPasswords ? 'Amaga' : 'Mostra' }}
            </button>
            <span class="spacer" />
            <button class="btn btn-ghost btn-sm" type="button" @click="closePassword">Cancel·la</button>
            <button
              class="btn btn-primary btn-sm"
              type="submit"
              :disabled="!canSubmit || changePassword.isPending.value"
            >
              {{ changePassword.isPending.value ? 'Desant…' : 'Desa i torna a entrar' }}
            </button>
          </div>
        </form>
      </div>
    </section>

    <!-- ── Sessions ───────────────────────────────────────────────────── -->
    <section class="card">
      <div class="card-head">
        <div>
          <h2 class="card-title">
            Sessions obertes
            <span v-if="sessions.length" class="count">{{ sessions.length }}</span>
          </h2>
          <p class="hint">Una fila per aplicació on has entrat amb aquest compte.</p>
        </div>
        <div v-if="sessions.length" class="head-actions">
          <template v-if="confirmingLogoutAll">
            <button class="btn btn-ghost btn-sm" type="button" @click="confirmingLogoutAll = false">
              Cancel·la
            </button>
            <button
              class="btn btn-danger btn-sm"
              type="button"
              :disabled="logoutAll.isPending.value"
              @click="logoutAll.mutate()"
            >
              {{ logoutAll.isPending.value ? 'Tancant…' : `Tanca-les totes (${sessions.length})` }}
            </button>
          </template>
          <button v-else class="btn btn-outline btn-sm" type="button" @click="confirmingLogoutAll = true">
            <AppIcon name="logout" />
            Tanca totes les sessions
          </button>
        </div>
      </div>

      <p v-if="sessionsQuery.isLoading.value" class="empty">Carregant sessions…</p>
      <p v-else-if="sessionsQuery.isError.value" class="card-body">
        <span class="notice notice-error">
          <AppIcon name="alert" :size="15" />
          <span>{{ (sessionsQuery.error.value as Error).message }}</span>
        </span>
      </p>
      <p v-else-if="!sessions.length" class="empty">Cap sessió oberta.</p>
      <ul v-else class="sessions">
        <li v-for="session in sessions" :key="session.id" class="session">
          <span class="session-icon">
            <AppIcon :name="describe(session).icon" :size="15" />
          </span>
          <span class="session-text">
            <strong class="truncate">
              {{ describe(session).name }}
              <span v-if="session.client_label" class="muted session-label">· {{ session.client_label }}</span>
            </strong>
            <span class="muted" :title="fullStamp(session.created_at)">
              Iniciada {{ fromNow(session.created_at) }}
            </span>
          </span>
          <span class="session-expiry muted" :title="fullStamp(session.expires_at)">
            Caduca {{ fromNow(session.expires_at) }}
          </span>
        </li>
      </ul>
    </section>

    <!-- ── This device ────────────────────────────────────────────────── -->
    <section v-if="platform.name === 'desktop'" class="card">
      <div class="card-head">
        <div>
          <h2 class="card-title">Aquest dispositiu</h2>
          <p class="hint">L'aplicació d'escriptori i el hub al qual parla.</p>
        </div>
        <span class="badge badge-neutral mono">{{ platform.version }}</span>
      </div>
      <dl class="facts">
        <div class="fact">
          <dt>Aplicació</dt>
          <dd>Cosecre per a escriptori</dd>
        </div>
        <div class="fact fact-wide">
          <dt>Hub</dt>
          <dd class="mono" :title="platform.hubUrl">{{ platform.hubUrl }}</dd>
        </div>
      </dl>
    </section>
  </div>
</template>

<style scoped>
.account-page {
  display: grid;
  grid-template-columns: minmax(0, 1fr);
  gap: 14px;
  max-width: var(--page-w-form);
}

/* ── Profile ─────────────────────────────────────────────────────────── */
.profile {
  display: flex;
  align-items: center;
  gap: 14px;
  padding: 16px;
  border-bottom: 1px solid var(--line);
}

.avatar {
  display: grid;
  flex-shrink: 0;
  place-items: center;
  width: 44px;
  height: 44px;
  border-radius: var(--r-full);
  background: var(--surface-3);
  color: var(--ink-500);
  font-size: var(--text-md);
  font-weight: 700;
  letter-spacing: 0.02em;
}

.avatar.role-admin {
  background: var(--accent-100);
  color: var(--accent-700);
}

.avatar.role-administratiu {
  background: var(--teal-100);
  color: var(--teal-700);
}

.avatar.role-professor {
  background: var(--gold-100);
  color: var(--gold-800);
}

.profile-text {
  display: grid;
  flex: 1;
  min-width: 0;
  gap: 1px;
  font-size: var(--text-base);
}

.profile-name {
  font-size: var(--text-lg);
  font-weight: 650;
  letter-spacing: -0.01em;
}

.name-row {
  display: flex;
  align-items: center;
  gap: 4px;
  min-width: 0;
}

.name-form {
  gap: 6px;
}

.name-input {
  flex: 1;
  min-width: 0;
  max-width: 360px;
  margin-right: 4px;
}

.profile-foot {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 6px;
  padding: 10px 16px;
  border-top: 1px solid var(--line);
  background: var(--surface-1);
  border-radius: 0 0 var(--r-lg) var(--r-lg);
  color: var(--ink-400);
  font-size: var(--text-sm);
}

.link {
  color: var(--accent-700);
  font-weight: 500;
}

.link:hover {
  text-decoration: underline;
}

/* Facts: cells in a row, divided by hairlines (as in Configuració). */
.facts {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  margin: 0;
}

.fact {
  display: grid;
  gap: 3px;
  min-width: 0;
  padding: 12px 16px;
}

.fact-wide {
  grid-column: span 2;
}

.fact + .fact {
  border-left: 1px solid var(--line);
}

.fact dt {
  color: var(--ink-400);
  font-size: var(--text-xs);
  font-weight: 600;
  letter-spacing: 0.04em;
  text-transform: uppercase;
}

.fact dd {
  margin: 0;
  overflow: hidden;
  font-size: var(--text-base);
  text-overflow: ellipsis;
  white-space: nowrap;
}

/* ── Setting row: label on the left, control on the right ────────────── */
.row {
  display: grid;
  grid-template-columns: minmax(0, 240px) minmax(0, 1fr);
  align-items: start;
  gap: 6px 28px;
  padding: 14px 16px;
}

.row-label {
  display: grid;
  gap: 2px;
  padding-top: 6px;
}

.row-label .label {
  color: var(--ink-700);
  font-size: var(--text-base);
  font-weight: 600;
  letter-spacing: 0;
  text-transform: none;
}

.row-control {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  min-height: 34px;
}

.dots {
  color: var(--ink-400);
  letter-spacing: 0.12em;
}

.password {
  display: grid;
  gap: 10px;
  animation: reveal 0.16s ease-out;
}

@keyframes reveal {
  from {
    opacity: 0;
    transform: translateY(-3px);
  }
}

.pair {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 10px;
}

.sublabel {
  color: var(--ink-400);
  font-size: var(--text-sm);
}

.checks {
  display: flex;
  flex-wrap: wrap;
  gap: 4px 14px;
  margin: 0;
  padding: 0;
  list-style: none;
  color: var(--ink-400);
  font-size: var(--text-sm);
}

.checks li {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  transition: color 0.12s ease;
}

.checks li.is-ok {
  color: var(--olive-700);
}

.password-actions {
  display: flex;
  align-items: center;
  gap: 4px;
}

.spacer {
  flex: 1;
}

/* ── Sessions ────────────────────────────────────────────────────────── */
.count {
  margin-left: 4px;
  padding: 0 6px;
  border-radius: var(--r-full);
  background: var(--surface-3);
  color: var(--ink-500);
  font-size: var(--text-xs);
  font-weight: 600;
  vertical-align: 1px;
}

.head-actions {
  display: flex;
  gap: 4px;
}

.sessions {
  margin: 0;
  padding: 0;
  list-style: none;
}

.session {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 11px 16px;
}

.session + .session {
  border-top: 1px solid var(--line);
}

.session-icon {
  display: grid;
  flex-shrink: 0;
  place-items: center;
  width: 28px;
  height: 28px;
  border-radius: var(--r-md);
  background: var(--surface-2);
  color: var(--ink-500);
}

.session-text {
  display: grid;
  flex: 1;
  min-width: 0;
  line-height: 1.35;
  font-size: var(--text-base);
}

.session-text strong {
  font-weight: 500;
}

.session-text .muted,
.session-expiry {
  font-size: var(--text-sm);
}

.session-label {
  font-weight: 400;
}

.session-expiry {
  flex-shrink: 0;
  white-space: nowrap;
}

@media (max-width: 720px) {
  .facts {
    grid-template-columns: minmax(0, 1fr);
  }

  .fact-wide {
    grid-column: auto;
  }

  .fact + .fact {
    border-left: 0;
    border-top: 1px solid var(--line);
  }

  /* One line per fact: label left, value right. */
  .fact {
    display: flex;
    align-items: baseline;
    justify-content: space-between;
    gap: 12px;
    padding: 9px 16px;
  }

  .fact dd {
    text-align: right;
  }

  .row {
    grid-template-columns: minmax(0, 1fr);
  }

  .row-label {
    padding-top: 0;
  }

  .pair {
    grid-template-columns: minmax(0, 1fr);
  }

  .name-form .name-row {
    flex-wrap: wrap;
  }

  .name-input {
    flex-basis: 100%;
    max-width: none;
    margin-right: 0;
  }

  .session-expiry {
    display: none;
  }
}

@media (prefers-reduced-motion: reduce) {
  .password {
    animation: none;
  }
}
</style>
