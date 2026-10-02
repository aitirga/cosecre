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
      error instanceof ApiError ? error.message : "No s'ha pogut canviar la contrasenya."
  },
})

function describeSession(client: string | null, label: string | null) {
  const name = client === 'desktop' ? 'Aplicació d\'escriptori' : client === 'web' ? 'Aplicació web' : (client ?? 'Client desconegut')
  return label ? `${name} · ${label}` : name
}
</script>

<template>
  <div class="account">
    <header class="page-head">
      <div>
        <h1 class="page-title">El meu compte</h1>
        <p class="page-lead">{{ auth.user.value?.email }}</p>
      </div>
      <span class="badge" :class="auth.isAdmin.value ? 'badge-accent' : 'badge-neutral'">
        {{ auth.isAdmin.value ? 'Administrador/a' : 'Membre' }}
      </span>
    </header>

    <section class="card">
      <div class="card-head"><h2 class="card-title">Change password</h2></div>
      <form class="card-body form" @submit.prevent="changePassword.mutate()">
        <label class="field">
          <span class="label">Contrasenya actual</span>
          <input
            v-model="passwordForm.current_password"
            class="input"
            type="password"
            autocomplete="current-password"
            required
          />
        </label>
        <label class="field">
          <span class="label">Contrasenya nova</span>
          <input
            v-model="passwordForm.new_password"
            class="input"
            type="password"
            autocomplete="new-password"
            minlength="8"
            required
          />
          <span class="hint">Mínim 8 caràcters. Es tancaran les altres sessions.</span>
        </label>
        <div class="span-2">
          <button class="btn btn-primary" type="submit" :disabled="changePassword.isPending.value">
            {{ changePassword.isPending.value ? 'Desant…' : 'Canvia la contrasenya' }}
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
          <h2 class="card-title">Sessions obertes</h2>
          <p class="hint">Una fila per aplicació amb sessió iniciada. Canviar la contrasenya les tanca totes.</p>
        </div>
      </div>
      <p v-if="sessionsQuery.isLoading.value" class="empty">Carregant sessions…</p>
      <div v-else class="table-scroll">
        <table class="table">
          <thead>
            <tr>
              <th>Aplicació</th>
              <th>Inici</th>
              <th>Caduca</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="session in sessionsQuery.data.value ?? []" :key="session.id">
              <td>{{ describeSession(session.client, session.client_label) }}</td>
              <td class="muted">{{ new Date(session.created_at).toLocaleString('ca-ES') }}</td>
              <td class="muted">{{ new Date(session.expires_at).toLocaleDateString('ca-ES') }}</td>
            </tr>
          </tbody>
        </table>
      </div>
    </section>

    <section v-if="platform.name === 'desktop'" class="card">
      <div class="card-head"><h2 class="card-title">Aquest dispositiu</h2></div>
      <dl class="card-body meta">
        <dt>Aplicació</dt>
        <dd>Cosecre per a escriptori {{ platform.version }}</dd>
        <dt>Hub</dt>
        <dd class="mono truncate">{{ platform.hubUrl }}</dd>
      </dl>
    </section>
  </div>
</template>

<style scoped>
.account {
  display: grid;
  /* minmax(0, …): wide tables scroll inside their card, not the page. */
  grid-template-columns: minmax(0, 1fr);
  gap: 16px;
  max-width: 720px;
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
