<script setup lang="ts">
import { computed, reactive, ref, watch } from 'vue'
import { useMutation, useQuery, useQueryClient } from '@tanstack/vue-query'

import { api, ApiError } from '../api/client'
import type { User } from '../api/types'
import AppIcon from '../components/AppIcon.vue'
import { useAuth } from '../composables/useAuth'
import { usePlatform } from '../platform'

const auth = useAuth()
const platform = usePlatform()
const queryClient = useQueryClient()

// ── Hub status ───────────────────────────────────────────────────────────────
const providersQuery = useQuery({
  queryKey: ['llm-providers'],
  queryFn: api.llmProviders,
  retry: false,
})

const capabilities = computed(() => {
  const hub = auth.state.hub
  if (!hub) return []
  return [
    { label: 'Model access', on: hub.capabilities.llm },
    { label: 'Google Sheets', on: hub.capabilities.google_sheets },
    { label: 'Documents', on: hub.capabilities.documents },
  ]
})

const modelOptions = computed(() => {
  const providers = providersQuery.data.value ?? []
  return Array.from(new Set(providers.flatMap((provider) => provider.models)))
})

// ── Workspace settings ───────────────────────────────────────────────────────
const settingsQuery = useQuery({ queryKey: ['settings'], queryFn: api.getSettings })

const form = reactive({
  spreadsheet_url: '',
  sheet_name: 'Factures',
  ticket_sheet_name: 'Tiquets',
  openai_model: 'gpt-5.4',
  extraction_prompt: '',
  polling_interval_seconds: 30,
})

watch(
  () => settingsQuery.data.value,
  (settings) => {
    if (!settings) return
    form.spreadsheet_url = settings.spreadsheet_url ?? ''
    form.sheet_name = settings.sheet_name
    form.ticket_sheet_name = settings.ticket_sheet_name
    form.openai_model = settings.openai_model
    form.extraction_prompt = settings.extraction_prompt
    form.polling_interval_seconds = settings.polling_interval_seconds
  },
  { immediate: true },
)

const saveMutation = useMutation({
  mutationFn: () =>
    api.updateSettings({ ...form, spreadsheet_url: form.spreadsheet_url || null }),
  onSuccess: () => queryClient.invalidateQueries({ queryKey: ['settings'] }),
})

// ── Team ─────────────────────────────────────────────────────────────────────
const usersQuery = useQuery({ queryKey: ['users'], queryFn: api.listUsers })

const newUser = reactive({ email: '', display_name: '', password: '', is_admin: false })
const showNewUser = ref(false)
const teamError = ref('')
const resetTarget = ref<User | null>(null)
const resetPassword = ref('')

function refreshUsers() {
  void queryClient.invalidateQueries({ queryKey: ['users'] })
}

function reportTeamError(error: unknown) {
  teamError.value = error instanceof ApiError ? error.message : 'The change could not be saved.'
}

const createUserMutation = useMutation({
  mutationFn: () =>
    api.createUser({
      email: newUser.email,
      password: newUser.password,
      display_name: newUser.display_name || null,
      is_admin: newUser.is_admin,
    }),
  onSuccess: () => {
    teamError.value = ''
    showNewUser.value = false
    Object.assign(newUser, { email: '', display_name: '', password: '', is_admin: false })
    refreshUsers()
  },
  onError: reportTeamError,
})

const updateUserMutation = useMutation({
  mutationFn: (input: { id: number; patch: Parameters<typeof api.updateUser>[1] }) =>
    api.updateUser(input.id, input.patch),
  onSuccess: () => {
    teamError.value = ''
    resetTarget.value = null
    resetPassword.value = ''
    refreshUsers()
  },
  onError: reportTeamError,
})

const isSelf = (user: User) => user.id === auth.user.value?.id
</script>

<template>
  <div class="settings">
    <header class="page-head">
      <div>
        <h1 class="page-title">Settings</h1>
        <p class="page-lead">Workspace configuration and accounts. Administrators only.</p>
      </div>
    </header>

    <!-- ── Hub ────────────────────────────────────────────────────────── -->
    <section class="card">
      <div class="card-head">
        <h2 class="card-title">Hub</h2>
        <span class="mono muted">{{ auth.state.hub?.version }}</span>
      </div>
      <div class="card-body hub">
        <dl class="meta">
          <dt>Server</dt>
          <dd>{{ auth.state.hub?.name ?? 'Unknown' }}</dd>
          <dt>API</dt>
          <dd class="mono">v{{ auth.state.hub?.api_version }} · {{ auth.state.hub?.api_prefix }}</dd>
          <dt>Registered apps</dt>
          <dd>{{ auth.state.hub?.apps.join(', ') || '—' }}</dd>
        </dl>
        <div class="caps">
          <span
            v-for="cap in capabilities"
            :key="cap.label"
            class="badge"
            :class="cap.on ? 'badge-olive' : 'badge-neutral'"
          >
            <AppIcon :name="cap.on ? 'check' : 'close'" :size="12" />
            {{ cap.label }}
          </span>
        </div>
        <p v-if="auth.state.hub && !auth.state.hub.capabilities.llm" class="notice notice-info">
          <AppIcon name="alert" :size="15" />
          <span>
            No model provider is configured on the hub, so extraction will fail. Set
            <code class="mono">COSECRE_OPENAI_API_KEY</code> and restart it.
          </span>
        </p>
      </div>
    </section>

    <!-- ── Workspace ──────────────────────────────────────────────────── -->
    <section class="card">
      <div class="card-head">
        <div>
          <h2 class="card-title">Google Sheets</h2>
          <p class="hint">
            Service-account credentials stay on the hub. This only chooses the target sheet.
          </p>
        </div>
      </div>

      <p v-if="settingsQuery.isLoading.value" class="empty">Loading settings…</p>
      <p v-else-if="settingsQuery.isError.value" class="card-body">
        <span class="notice notice-error">
          <AppIcon name="alert" :size="15" />
          <span>{{ (settingsQuery.error.value as Error).message }}</span>
        </span>
      </p>

      <form v-else class="card-body grid" @submit.prevent="saveMutation.mutate()">
        <label class="field span-2">
          <span class="label">Spreadsheet URL</span>
          <input
            v-model="form.spreadsheet_url"
            class="input"
            type="url"
            placeholder="https://docs.google.com/spreadsheets/d/…"
          />
          <span class="hint">Share the sheet with the service account, or writes will fail.</span>
        </label>

        <label class="field">
          <span class="label">Invoices tab</span>
          <input v-model="form.sheet_name" class="input" type="text" required />
        </label>

        <label class="field">
          <span class="label">Tickets tab</span>
          <input v-model="form.ticket_sheet_name" class="input" type="text" required />
        </label>

        <label class="field">
          <span class="label">Extraction model</span>
          <input
            v-model="form.openai_model"
            class="input"
            type="text"
            list="cosecre-models"
            required
          />
          <datalist id="cosecre-models">
            <option v-for="model in modelOptions" :key="model" :value="model" />
          </datalist>
        </label>

        <label class="field">
          <span class="label">Poll interval (seconds)</span>
          <input
            v-model.number="form.polling_interval_seconds"
            class="input"
            type="number"
            min="10"
            max="300"
          />
        </label>

        <label class="field span-2">
          <span class="label">Extra extraction instructions</span>
          <textarea
            v-model="form.extraction_prompt"
            class="textarea"
            rows="5"
            placeholder="Appended to the built-in prompt. Leave empty to use the default."
          />
        </label>

        <div class="row span-2">
          <button class="btn btn-primary" type="submit" :disabled="saveMutation.isPending.value">
            {{ saveMutation.isPending.value ? 'Saving…' : 'Save settings' }}
          </button>
          <span v-if="saveMutation.isSuccess.value" class="badge badge-olive">
            <AppIcon name="check" :size="12" />
            Saved
          </span>
        </div>

        <p v-if="saveMutation.isError.value" class="notice notice-error span-2">
          <AppIcon name="alert" :size="15" />
          <span>{{ (saveMutation.error.value as Error).message }}</span>
        </p>
      </form>
    </section>

    <!-- ── Team ───────────────────────────────────────────────────────── -->
    <section class="card">
      <div class="card-head">
        <div>
          <h2 class="card-title">Team</h2>
          <p class="hint">Accounts are disabled rather than deleted, so their history survives.</p>
        </div>
        <button class="btn btn-outline" type="button" @click="showNewUser = true">
          <AppIcon name="plus" />
          Add member
        </button>
      </div>

      <p v-if="usersQuery.isLoading.value" class="empty">Loading accounts…</p>
      <div v-else class="table-scroll">
        <table class="table">
          <thead>
            <tr>
              <th>Account</th>
              <th>Role</th>
              <th>Last sign-in</th>
              <th class="actions"><span class="sr-only">Actions</span></th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="user in usersQuery.data.value ?? []" :key="user.id">
              <td>
                <div class="account-cell">
                  <strong>{{ user.display_name || user.email }}</strong>
                  <span v-if="user.display_name" class="muted">{{ user.email }}</span>
                </div>
              </td>
              <td>
                <span class="badge" :class="user.is_admin ? 'badge-accent' : 'badge-neutral'">
                  {{ user.is_admin ? 'Administrator' : 'Member' }}
                </span>
                <span v-if="!user.is_active" class="badge badge-danger disabled-badge">
                  Disabled
                </span>
              </td>
              <td class="muted">
                {{ user.last_login_at ? new Date(user.last_login_at).toLocaleDateString() : 'Never' }}
              </td>
              <td class="actions">
                <div class="row-actions">
                  <button
                    class="btn btn-ghost btn-sm"
                    type="button"
                    @click="
                      () => {
                        resetTarget = user
                        resetPassword = ''
                      }
                    "
                  >
                    <AppIcon name="lock" />
                    Reset
                  </button>
                  <button
                    class="btn btn-outline btn-sm"
                    type="button"
                    :disabled="isSelf(user) || updateUserMutation.isPending.value"
                    @click="
                      updateUserMutation.mutate({ id: user.id, patch: { is_admin: !user.is_admin } })
                    "
                  >
                    {{ user.is_admin ? 'Make member' : 'Make admin' }}
                  </button>
                  <button
                    class="btn btn-ghost btn-sm"
                    type="button"
                    :disabled="isSelf(user) || updateUserMutation.isPending.value"
                    @click="
                      updateUserMutation.mutate({
                        id: user.id,
                        patch: { is_active: !user.is_active },
                      })
                    "
                  >
                    {{ user.is_active ? 'Disable' : 'Enable' }}
                  </button>
                </div>
              </td>
            </tr>
          </tbody>
        </table>
      </div>

      <p v-if="teamError" class="card-body">
        <span class="notice notice-error">
          <AppIcon name="alert" :size="15" />
          <span>{{ teamError }}</span>
        </span>
      </p>
    </section>

    <component :is="platform.settingsPanel" v-if="platform.settingsPanel" />

    <!-- ── Dialogs ────────────────────────────────────────────────────── -->
    <Teleport to="body">
      <div v-if="showNewUser" class="overlay" @click.self="showNewUser = false">
        <form class="dialog" @submit.prevent="createUserMutation.mutate()">
          <h2 class="dialog-title">Add a team member</h2>
          <label class="field">
            <span class="label">Email</span>
            <input v-model="newUser.email" class="input" type="email" required />
          </label>
          <label class="field">
            <span class="label">Name (optional)</span>
            <input v-model="newUser.display_name" class="input" type="text" />
          </label>
          <label class="field">
            <span class="label">Temporary password</span>
            <input
              v-model="newUser.password"
              class="input"
              type="text"
              minlength="8"
              required
              autocomplete="off"
            />
            <span class="hint">
              At least 8 characters. Share it over a channel you trust; they can change it from
              their account page.
            </span>
          </label>
          <label class="checkbox">
            <input v-model="newUser.is_admin" type="checkbox" />
            <span>Administrator — can manage settings and accounts</span>
          </label>
          <div class="dialog-actions">
            <button class="btn btn-outline" type="button" @click="showNewUser = false">
              Cancel
            </button>
            <button
              class="btn btn-primary"
              type="submit"
              :disabled="createUserMutation.isPending.value"
            >
              {{ createUserMutation.isPending.value ? 'Creating…' : 'Create account' }}
            </button>
          </div>
        </form>
      </div>
    </Teleport>

    <Teleport to="body">
      <div v-if="resetTarget" class="overlay" @click.self="resetTarget = null">
        <form
          class="dialog"
          @submit.prevent="
            updateUserMutation.mutate({
              id: resetTarget!.id,
              patch: { password: resetPassword },
            })
          "
        >
          <h2 class="dialog-title">Reset password</h2>
          <p class="subtle">
            Sets a new password for <strong>{{ resetTarget.email }}</strong> and signs them out
            everywhere.
          </p>
          <label class="field">
            <span class="label">New password</span>
            <input
              v-model="resetPassword"
              class="input"
              type="text"
              minlength="8"
              required
              autocomplete="off"
            />
          </label>
          <div class="dialog-actions">
            <button class="btn btn-outline" type="button" @click="resetTarget = null">Cancel</button>
            <button
              class="btn btn-primary"
              type="submit"
              :disabled="updateUserMutation.isPending.value"
            >
              {{ updateUserMutation.isPending.value ? 'Saving…' : 'Set password' }}
            </button>
          </div>
        </form>
      </div>
    </Teleport>
  </div>
</template>

<style scoped>
.settings {
  display: grid;
  gap: 16px;
  max-width: 880px;
}

.hub {
  display: grid;
  gap: 12px;
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

.caps {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 12px;
}

.span-2 {
  grid-column: 1 / -1;
}

.row {
  display: flex;
  align-items: center;
  gap: 10px;
}

.account-cell {
  display: grid;
  line-height: 1.35;
}

.account-cell .muted {
  font-size: var(--text-sm);
}

.disabled-badge {
  margin-left: 5px;
}

.row-actions {
  display: inline-flex;
  gap: 4px;
}

.checkbox {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: var(--text-base);
  color: var(--ink-500);
}

.checkbox input {
  accent-color: var(--accent-700);
}

code {
  padding: 1px 4px;
  border-radius: var(--r-xs);
  background: var(--surface-2);
}

@media (max-width: 720px) {
  .grid {
    grid-template-columns: minmax(0, 1fr);
  }
}
</style>
