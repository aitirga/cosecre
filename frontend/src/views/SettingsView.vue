<script setup lang="ts">
import { computed, reactive, watch } from 'vue'
import { useMutation, useQuery, useQueryClient } from '@tanstack/vue-query'

import { api } from '../api/client'
import AppIcon from '../components/AppIcon.vue'
import BackupsPanel from '../components/BackupsPanel.vue'
import MigrationPanel from '../components/MigrationPanel.vue'
import DuplicatesPanel from '../components/DuplicatesPanel.vue'
import HistoryPanel from '../components/HistoryPanel.vue'
import OriginalsPanel from '../components/OriginalsPanel.vue'
import TeamPanel from '../components/TeamPanel.vue'
import { useAuth } from '../composables/useAuth'
import { usePreferences } from '../composables/usePreferences'
import { usePlatform } from '../platform'

const auth = useAuth()
const preferences = usePreferences()
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
  iban_general: '',
  iban_material: '',
  iban_menjador: '',
  prepaid_card_number: '',
  caixeta_spreadsheet_url: '',
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
    form.iban_general = settings.iban_general ?? ''
    form.iban_material = settings.iban_material ?? ''
    form.iban_menjador = settings.iban_menjador ?? ''
    form.prepaid_card_number = settings.prepaid_card_number ?? ''
    form.caixeta_spreadsheet_url = settings.caixeta_spreadsheet_url ?? ''
  },
  { immediate: true },
)

const saveMutation = useMutation({
  mutationFn: () =>
    api.updateSettings({ ...form, spreadsheet_url: form.spreadsheet_url || null }),
  onSuccess: () => queryClient.invalidateQueries({ queryKey: ['settings'] }),
})
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

    <!-- ── This browser ───────────────────────────────────────────────── -->
    <section class="card">
      <div class="card-head">
        <div>
          <h2 class="card-title">Preferències</h2>
          <p class="hint">Només d'aquest navegador; no canvien res per a la resta de l'equip.</p>
        </div>
      </div>
      <div class="card-body">
        <label class="toggle">
          <input v-model="preferences.openOnCapture" type="checkbox" />
          <span class="toggle-text">
            <span class="label">Obre la fitxa en fer una foto o pujar un document</span>
            <span class="hint">
              La fitxa s'obre de seguida i mostra en lila els camps que la IA està llegint. Pots omplir
              els teus alhora: es desen sols i la IA no els sobreescriu.
            </span>
          </span>
        </label>
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

        <h3 class="subhead span-2">Extractes bancaris</h3>
        <p class="hint span-2">
          L'IBAN del títol de cada Excel de La Caixa diu de quin compte és. Si en arriba un de desconegut,
          es pregunta un cop i es desa aquí.
        </p>
        <label class="field">
          <span class="label">IBAN compte General</span>
          <input v-model="form.iban_general" class="input mono" type="text" placeholder="ES00 0000 0000 0000 0000 0000" />
        </label>
        <label class="field">
          <span class="label">IBAN compte de Material i Sortides</span>
          <input v-model="form.iban_material" class="input mono" type="text" />
        </label>
        <label class="field">
          <span class="label">IBAN compte de Menjador</span>
          <input v-model="form.iban_menjador" class="input mono" type="text" />
        </label>
        <label class="field">
          <span class="label">Targeta de prepagament</span>
          <input v-model="form.prepaid_card_number" class="input mono" type="text" placeholder="4047 0001 …" />
        </label>
        <label class="field span-2">
          <span class="label">Full de la caixeta d'efectiu</span>
          <input
            v-model="form.caixeta_spreadsheet_url"
            class="input"
            type="url"
            placeholder="https://docs.google.com/spreadsheets/d/…"
          />
          <span class="hint">Es llegeixen les pestanyes CAIXETA'AA cada cop que algú entra a l'aplicació.</span>
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

    <HistoryPanel />

    <DuplicatesPanel />

    <TeamPanel />

    <component :is="platform.settingsPanel" v-if="platform.settingsPanel" />
  </div>
</template>

<style scoped>
.toggle {
  display: flex;
  align-items: flex-start;
  gap: 10px;
  cursor: pointer;
}

.toggle input {
  margin-top: 3px;
  accent-color: var(--accent-600, var(--accent-500));
}

.toggle-text {
  display: grid;
  gap: 2px;
}

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

.subhead {
  margin: 8px 0 0;
  padding-top: 12px;
  border-top: 1px solid var(--line);
  font-size: var(--text-md);
  font-weight: 600;
}
</style>
