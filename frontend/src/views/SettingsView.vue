<script setup lang="ts">
import { computed, reactive, ref, watch } from 'vue'
import { useMutation, useQuery, useQueryClient } from '@tanstack/vue-query'

import { api, ApiError } from '../api/client'
import type { User } from '../api/types'
import AppIcon from '../components/AppIcon.vue'
import BackupsPanel from '../components/BackupsPanel.vue'
import MigrationPanel from '../components/MigrationPanel.vue'
import OriginalsPanel from '../components/OriginalsPanel.vue'
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
    { label: 'Model de visió (OpenAI)', on: hub.capabilities.llm },
    { label: 'Classificador Jev', on: Boolean(hub.capabilities.classifier) },
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
  registry_sheet_name: 'Registre documents comptables',
  sheet_name: 'Factures',
  ticket_sheet_name: 'Tiquets',
  openai_model: 'gpt-6-luna',
  extraction_prompt: '',
  polling_interval_seconds: 30,
})

watch(
  () => settingsQuery.data.value,
  (settings) => {
    if (!settings) return
    form.spreadsheet_url = settings.spreadsheet_url ?? ''
    form.registry_sheet_name = settings.registry_sheet_name
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
  teamError.value = error instanceof ApiError ? error.message : "No s'ha pogut desar el canvi."
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
        <h1 class="page-title">Configuració</h1>
        <p class="page-lead">Full de càlcul, models, migració, còpies de seguretat, originals i comptes.</p>
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
          <dt>Servidor</dt>
          <dd>{{ auth.state.hub?.name ?? 'Desconegut' }}</dd>
          <dt>API</dt>
          <dd class="mono">v{{ auth.state.hub?.api_version }} · {{ auth.state.hub?.api_prefix }}</dd>
          <dt>Aplicacions</dt>
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
            El hub no té cap model configurat i no podrà llegir documents. Defineix
            <code class="mono">COSECRE_OPENAI_API_KEY</code> i reinicia'l.
          </span>
        </p>
      </div>
    </section>

    <!-- ── Workspace ──────────────────────────────────────────────────── -->
    <section class="card">
      <div class="card-head">
        <div>
          <h2 class="card-title">Full de càlcul i models</h2>
          <p class="hint">
            Les credencials de Google es queden al servidor; aquí només es tria el full.
          </p>
        </div>
      </div>

      <p v-if="settingsQuery.isLoading.value" class="empty">Carregant…</p>
      <p v-else-if="settingsQuery.isError.value" class="card-body">
        <span class="notice notice-error">
          <AppIcon name="alert" :size="15" />
          <span>{{ (settingsQuery.error.value as Error).message }}</span>
        </span>
      </p>

      <form v-else class="card-body grid" @submit.prevent="saveMutation.mutate()">
        <label class="field span-2">
          <span class="label">URL del full de càlcul</span>
          <input
            v-model="form.spreadsheet_url"
            class="input"
            type="url"
            placeholder="https://docs.google.com/spreadsheets/d/…"
          />
          <span class="hint">Comparteix el full amb el compte de servei, o no s'hi podrà escriure.</span>
        </label>

        <label class="field span-2">
          <span class="label">Pestanya del registre</span>
          <input v-model="form.registry_sheet_name" class="input" type="text" required />
          <span class="hint">Si no existeix, es crea amb les columnes, formats i desplegables.</span>
        </label>

        <label class="field">
          <span class="label">Pestanya antiga de factures</span>
          <input v-model="form.sheet_name" class="input" type="text" required />
        </label>

        <label class="field">
          <span class="label">Pestanya antiga de tiquets</span>
          <input v-model="form.ticket_sheet_name" class="input" type="text" required />
        </label>

        <label class="field">
          <span class="label">Model de lectura</span>
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
          <span class="label">Interval de consulta (segons)</span>
          <input
            v-model.number="form.polling_interval_seconds"
            class="input"
            type="number"
            min="10"
            max="300"
          />
        </label>

        <label class="field span-2">
          <span class="label">Instruccions addicionals per a la lectura</span>
          <textarea
            v-model="form.extraction_prompt"
            class="textarea"
            rows="5"
            placeholder="S'afegeixen a les instruccions de sèrie. Deixa-ho buit per no canviar res."
          />
        </label>

        <div class="row span-2">
          <button class="btn btn-primary" type="submit" :disabled="saveMutation.isPending.value">
            {{ saveMutation.isPending.value ? 'Desant…' : 'Desa la configuració' }}
          </button>
          <span v-if="saveMutation.isSuccess.value" class="badge badge-olive">
            <AppIcon name="check" :size="12" />
            Desat
          </span>
          <span
            class="badge"
            :class="settingsQuery.data.value?.classifier_configured ? 'badge-olive' : 'badge-neutral'"
            title="Jev dona una segona opinió sobre el tipus de document i el pagament"
          >
            <AppIcon :name="settingsQuery.data.value?.classifier_configured ? 'check' : 'close'" :size="12" />
            Jev {{ settingsQuery.data.value?.classifier_configured ? 'actiu' : 'no configurat' }}
          </span>
          <span
            class="badge"
            :class="settingsQuery.data.value?.drive_folder_configured ? 'badge-olive' : 'badge-gold'"
          >
            <AppIcon :name="settingsQuery.data.value?.drive_folder_configured ? 'check' : 'alert'" :size="12" />
            {{ settingsQuery.data.value?.drive_folder_configured ? 'Carpeta de Drive' : 'Sense carpeta de Drive' }}
          </span>
        </div>

        <p v-if="saveMutation.isError.value" class="notice notice-error span-2">
          <AppIcon name="alert" :size="15" />
          <span>{{ (saveMutation.error.value as Error).message }}</span>
        </p>
      </form>
    </section>

    <MigrationPanel
      :legacy-tabs="[form.sheet_name, form.ticket_sheet_name]"
      :registry-tab="form.registry_sheet_name"
    />

    <BackupsPanel />

    <OriginalsPanel />

    <!-- ── Team ───────────────────────────────────────────────────────── -->
    <section class="card">
      <div class="card-head">
        <div>
          <h2 class="card-title">Equip</h2>
          <p class="hint">Els comptes es desactiven en lloc d'esborrar-se, i així se'n conserva l'historial.</p>
        </div>
        <button class="btn btn-outline" type="button" @click="showNewUser = true">
          <AppIcon name="plus" />
          Afegeix membre
        </button>
      </div>

      <p v-if="usersQuery.isLoading.value" class="empty">Carregant comptes…</p>
      <div v-else class="table-scroll">
        <table class="table">
          <thead>
            <tr>
              <th>Compte</th>
              <th>Rol</th>
              <th>Últim accés</th>
              <th class="actions"><span class="sr-only">Accions</span></th>
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
                  {{ user.is_admin ? 'Administrador/a' : 'Membre' }}
                </span>
                <span v-if="!user.is_active" class="badge badge-danger disabled-badge">
                  Desactivat
                </span>
              </td>
              <td class="muted">
                {{ user.last_login_at ? new Date(user.last_login_at).toLocaleDateString('ca-ES') : 'Mai' }}
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
                    Contrasenya
                  </button>
                  <button
                    class="btn btn-outline btn-sm"
                    type="button"
                    :disabled="isSelf(user) || updateUserMutation.isPending.value"
                    @click="
                      updateUserMutation.mutate({ id: user.id, patch: { is_admin: !user.is_admin } })
                    "
                  >
                    {{ user.is_admin ? 'Fes-lo membre' : 'Fes-lo admin' }}
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
                    {{ user.is_active ? 'Desactiva' : 'Activa' }}
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
          <h2 class="dialog-title">Afegeix un membre</h2>
          <label class="field">
            <span class="label">Correu electrònic</span>
            <input v-model="newUser.email" class="input" type="email" required />
          </label>
          <label class="field">
            <span class="label">Nom (opcional)</span>
            <input v-model="newUser.display_name" class="input" type="text" />
          </label>
          <label class="field">
            <span class="label">Contrasenya provisional</span>
            <input
              v-model="newUser.password"
              class="input"
              type="text"
              minlength="8"
              required
              autocomplete="off"
            />
            <span class="hint">
              Mínim 8 caràcters. Comparteix-la per un canal de confiança; la persona la pot canviar
              des del seu compte.
            </span>
          </label>
          <label class="checkbox">
            <input v-model="newUser.is_admin" type="checkbox" />
            <span>Administrador/a — pot gestionar la configuració i els comptes</span>
          </label>
          <div class="dialog-actions">
            <button class="btn btn-outline" type="button" @click="showNewUser = false">
              Cancel·la
            </button>
            <button
              class="btn btn-primary"
              type="submit"
              :disabled="createUserMutation.isPending.value"
            >
              {{ createUserMutation.isPending.value ? 'Creant…' : 'Crea el compte' }}
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
          <h2 class="dialog-title">Canvia la contrasenya</h2>
          <p class="subtle">
            Posa una contrasenya nova a <strong>{{ resetTarget.email }}</strong> i en tanca totes
            les sessions.
          </p>
          <label class="field">
            <span class="label">Contrasenya nova</span>
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
            <button class="btn btn-outline" type="button" @click="resetTarget = null">Cancel·la</button>
            <button
              class="btn btn-primary"
              type="submit"
              :disabled="updateUserMutation.isPending.value"
            >
              {{ updateUserMutation.isPending.value ? 'Desant…' : 'Desa la contrasenya' }}
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
  /* minmax(0, …): wide tables scroll inside their card, not the page. */
  grid-template-columns: minmax(0, 1fr);
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
