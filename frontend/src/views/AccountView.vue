<script setup lang="ts">
import { reactive, ref } from 'vue'
import { useMutation, useQuery, useQueryClient } from '@tanstack/vue-query'

import { api, ApiError } from '../api/client'
import AppIcon from '../components/AppIcon.vue'
import { useAuth } from '../composables/useAuth'
import { usePlatform } from '../platform'

const auth = useAuth()
const platform = usePlatform()
const queryClient = useQueryClient()

const sessionsQuery = useQuery({ queryKey: ['sessions'], queryFn: api.sessions })

const passwordForm = reactive({ current_password: '', new_password: '' })
const passwordError = ref('')
const passwordDone = ref('')

const changePassword = useMutation({
  mutationFn: () => api.changePassword({ ...passwordForm }),
  onSuccess: (result) => {
    passwordError.value = ''
    passwordDone.value = result.message
    passwordForm.current_password = ''
    passwordForm.new_password = ''
    // Changing a password revokes every other session, so the list is stale.
    void queryClient.invalidateQueries({ queryKey: ['sessions'] })
  },
  onError: (error) => {
    passwordDone.value = ''
    passwordError.value =
      error instanceof ApiError ? error.message : 'The password could not be changed.'
  },
})

function describeSession(client: string | null, label: string | null) {
  const name = client === 'desktop' ? 'Desktop app' : client === 'web' ? 'Web app' : (client ?? 'Unknown client')
  return label ? `${name} · ${label}` : name
}
</script>

<template>
  <div class="account">
    <header class="page-head">
      <div>
        <h1 class="page-title">Account</h1>
        <p class="page-lead">{{ auth.user.value?.email }}</p>
      </div>
      <span class="badge" :class="auth.isAdmin.value ? 'badge-accent' : 'badge-neutral'">
        {{ auth.isAdmin.value ? 'Administrator' : 'Member' }}
      </span>
    </header>

    <section class="card">
      <div class="card-head"><h2 class="card-title">Change password</h2></div>
      <form class="card-body form" @submit.prevent="changePassword.mutate()">
        <label class="field">
          <span class="label">Current password</span>
          <input
            v-model="passwordForm.current_password"
            class="input"
            type="password"
            autocomplete="current-password"
            required
          />
        </label>
        <label class="field">
          <span class="label">New password</span>
          <input
            v-model="passwordForm.new_password"
            class="input"
            type="password"
            autocomplete="new-password"
            minlength="8"
            required
          />
          <span class="hint">At least 8 characters. Your other sessions will be signed out.</span>
        </label>
        <div class="span-2">
          <button class="btn btn-primary" type="submit" :disabled="changePassword.isPending.value">
            {{ changePassword.isPending.value ? 'Saving…' : 'Update password' }}
          </button>
        </div>
        <p v-if="passwordDone" class="notice notice-success span-2">
          <AppIcon name="check" :size="15" />
          <span>{{ passwordDone }}</span>
        </p>
        <p v-if="passwordError" class="notice notice-error span-2">
          <AppIcon name="alert" :size="15" />
          <span>{{ passwordError }}</span>
        </p>
      </form>
    </section>

    <section class="card">
      <div class="card-head">
        <div>
          <h2 class="card-title">Active sessions</h2>
          <p class="hint">One row per signed-in app. Changing your password ends all of them.</p>
        </div>
      </div>
      <p v-if="sessionsQuery.isLoading.value" class="empty">Loading sessions…</p>
      <div v-else class="table-scroll">
        <table class="table">
          <thead>
            <tr>
              <th>Client</th>
              <th>Signed in</th>
              <th>Expires</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="session in sessionsQuery.data.value ?? []" :key="session.id">
              <td>{{ describeSession(session.client, session.client_label) }}</td>
              <td class="muted">{{ new Date(session.created_at).toLocaleString() }}</td>
              <td class="muted">{{ new Date(session.expires_at).toLocaleDateString() }}</td>
            </tr>
          </tbody>
        </table>
      </div>
    </section>

    <section v-if="platform.name === 'desktop'" class="card">
      <div class="card-head"><h2 class="card-title">This device</h2></div>
      <dl class="card-body meta">
        <dt>App</dt>
        <dd>Cosecre Desktop {{ platform.version }}</dd>
        <dt>Hub</dt>
        <dd class="mono truncate">{{ platform.hubUrl }}</dd>
      </dl>
    </section>
  </div>
</template>

<style scoped>
.account {
  display: grid;
  gap: 16px;
  max-width: 720px;
}

.page-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
}

.page-title {
  font-size: var(--text-xl);
}

.page-lead {
  margin-top: 2px;
  font-size: var(--text-base);
  color: var(--ink-400);
}

.form {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 12px;
}

.span-2 {
  grid-column: 1 / -1;
}

.meta {
  display: grid;
  grid-template-columns: auto minmax(0, 1fr);
  gap: 5px 16px;
  margin: 0;
  font-size: var(--text-base);
}

.meta dt {
  color: var(--ink-400);
}

.meta dd {
  margin: 0;
  min-width: 0;
}

@media (max-width: 640px) {
  .form {
    grid-template-columns: minmax(0, 1fr);
  }
}
</style>
