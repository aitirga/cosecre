<script setup lang="ts">
import { computed, nextTick, reactive, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useMutation, useQuery, useQueryClient } from '@tanstack/vue-query'

import { api } from '../api/client'
import type { WorkspaceSettings } from '../api/types'
import AppIcon from '../components/AppIcon.vue'
import BackupsPanel from '../components/BackupsPanel.vue'
import DuplicatesPanel from '../components/DuplicatesPanel.vue'
import HistoryPanel from '../components/HistoryPanel.vue'
import MigrationPanel from '../components/MigrationPanel.vue'
import OriginalsPanel from '../components/OriginalsPanel.vue'
import TeamPanel from '../components/TeamPanel.vue'
import type { IconName } from '../components/icons'
import { useAuth } from '../composables/useAuth'
import { usePreferences } from '../composables/usePreferences'
import { usePlatform } from '../platform'

const auth = useAuth()
const preferences = usePreferences()
const platform = usePlatform()
const queryClient = useQueryClient()
const route = useRoute()
const router = useRouter()

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
    {
      label: 'Model de visió',
      detail: 'Llegeix factures i tiquets (OpenAI).',
      icon: 'sparkles' as IconName,
      on: hub.capabilities.llm,
    },
    {
      label: 'Classificador Jev',
      detail: 'Segona opinió sobre el tipus i el pagament.',
      icon: 'check' as IconName,
      on: Boolean(hub.capabilities.classifier),
    },
    {
      label: 'Google Sheets',
      detail: 'Escriu el registre al full de càlcul.',
      icon: 'sheet' as IconName,
      on: hub.capabilities.google_sheets,
    },
    {
      label: 'Documents',
      detail: 'Desa els originals al servidor.',
      icon: 'invoice' as IconName,
      on: hub.capabilities.documents,
    },
  ]
})

const modelOptions = computed(() => {
  const providers = providersQuery.data.value ?? []
  return Array.from(new Set(providers.flatMap((provider) => provider.models)))
})

// ── Workspace settings ───────────────────────────────────────────────────────
// One form, edited from three tabs. It is saved as a whole, so the save bar
// floats over every tab while anything differs from what the hub holds.
const settingsQuery = useQuery({ queryKey: ['settings'], queryFn: api.getSettings })

type EditableSettings = Required<Omit<WorkspaceSettings, 'classifier_configured' | 'drive_folder_configured'>>

function fromSettings(settings: WorkspaceSettings): EditableSettings {
  return {
    spreadsheet_url: settings.spreadsheet_url ?? '',
    registry_sheet_name: settings.registry_sheet_name,
    sheet_name: settings.sheet_name,
    ticket_sheet_name: settings.ticket_sheet_name,
    openai_model: settings.openai_model,
    extraction_prompt: settings.extraction_prompt,
    polling_interval_seconds: settings.polling_interval_seconds,
    iban_general: settings.iban_general ?? '',
    iban_material: settings.iban_material ?? '',
    iban_menjador: settings.iban_menjador ?? '',
    prepaid_card_number: settings.prepaid_card_number ?? '',
    caixeta_spreadsheet_url: settings.caixeta_spreadsheet_url ?? '',
  }
}

const form = reactive<EditableSettings>({
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
const saved = ref<EditableSettings | null>(null)

watch(
  () => settingsQuery.data.value,
  (settings) => {
    if (!settings) return
    saved.value = fromSettings(settings)
    Object.assign(form, saved.value)
  },
  { immediate: true },
)

const SHEET_FIELDS = ['spreadsheet_url', 'registry_sheet_name', 'sheet_name', 'ticket_sheet_name'] as const
const AI_FIELDS = ['openai_model', 'polling_interval_seconds', 'extraction_prompt'] as const
const BANK_FIELDS = [
  'iban_general',
  'iban_material',
  'iban_menjador',
  'prepaid_card_number',
  'caixeta_spreadsheet_url',
] as const

function changed(fields: readonly (keyof EditableSettings)[]) {
  const base = saved.value
  return Boolean(base) && fields.some((field) => form[field] !== base![field])
}

const sheetDirty = computed(() => changed(SHEET_FIELDS))
const aiDirty = computed(() => changed(AI_FIELDS))
const bankDirty = computed(() => changed(BANK_FIELDS))
const dirty = computed(() => sheetDirty.value || aiDirty.value || bankDirty.value)

const dirtyWhere = computed(() =>
  [sheetDirty.value && 'full de càlcul', aiDirty.value && 'lectura', bankDirty.value && 'banc']
    .filter(Boolean)
    .join(', '),
)

function discard() {
  if (saved.value) Object.assign(form, saved.value)
  saveMutation.reset()
}

const justSaved = ref(false)
let savedTimer: ReturnType<typeof setTimeout> | undefined

const saveMutation = useMutation({
  mutationFn: () =>
    api.updateSettings({ ...form, spreadsheet_url: form.spreadsheet_url || null }),
  onSuccess: (settings) => {
    queryClient.setQueryData(['settings'], settings)
    void queryClient.invalidateQueries({ queryKey: ['settings'] })
    justSaved.value = true
    clearTimeout(savedTimer)
    savedTimer = setTimeout(() => (justSaved.value = false), 2400)
  },
})

const spreadsheetHref = computed(() => {
  const url = saved.value?.spreadsheet_url
  return url && /^https?:\/\//.test(url) ? url : null
})

// ── Team ─────────────────────────────────────────────────────────────────────
// Shares TeamPanel's cache entry; only read here for the count on the tab.
const usersQuery = useQuery({ queryKey: ['users'], queryFn: api.listUsers })
const activeUsers = computed(() => (usersQuery.data.value ?? []).filter((user) => user.is_active).length)

// ── Tabs ─────────────────────────────────────────────────────────────────────
// The active tab lives in `?tab=`, so a link (or the register's "restore from
// Configuració") can land on the right one and a reload keeps it.
type TabId = 'general' | 'sheet' | 'ai' | 'bank' | 'data' | 'history' | 'team' | 'app'

interface Tab {
  id: TabId
  label: string
  icon: IconName
  /** gold = needs attention, accent = unsaved edits. */
  dot?: 'gold' | 'accent'
  count?: number
}

const tabs = computed<Tab[]>(() => {
  const hub = auth.state.hub
  const settings = settingsQuery.data.value
  const list: Tab[] = [
    {
      id: 'general',
      label: 'General',
      icon: 'server',
      dot: hub && !hub.capabilities.llm ? 'gold' : undefined,
    },
    {
      id: 'sheet',
      label: 'Full de càlcul',
      icon: 'sheet',
      dot: sheetDirty.value
        ? 'accent'
        : settings && (!settings.spreadsheet_url || !settings.drive_folder_configured)
          ? 'gold'
          : undefined,
    },
    { id: 'ai', label: 'Lectura amb IA', icon: 'sparkles', dot: aiDirty.value ? 'accent' : undefined },
    { id: 'bank', label: 'Banc', icon: 'bank', dot: bankDirty.value ? 'accent' : undefined },
    { id: 'data', label: 'Còpies', icon: 'database' },
    { id: 'history', label: 'Historial', icon: 'activity' },
    { id: 'team', label: 'Equip', icon: 'users', count: usersQuery.data.value ? activeUsers.value : undefined },
  ]
  if (platform.settingsPanel) list.push({ id: 'app', label: 'Aplicació', icon: 'monitor' })
  return list
})

const active = computed<TabId>(() => tabs.value.find((tab) => tab.id === route.query.tab)?.id ?? 'general')

function select(id: TabId) {
  if (id === active.value) return
  void router.replace({ query: { ...route.query, tab: id === 'general' ? undefined : id } })
}

const tabRefs = ref<HTMLButtonElement[]>([])

// On a phone the bar scrolls sideways; keep the open tab in sight.
watch(
  active,
  async (id) => {
    await nextTick()
    const index = tabs.value.findIndex((tab) => tab.id === id)
    const button = tabRefs.value[index]
    const bar = button?.parentElement
    // Scrolls the bar alone: scrollIntoView would drag the page along with it.
    if (button && bar) bar.scrollLeft = button.offsetLeft - (bar.clientWidth - button.offsetWidth) / 2
  },
  { immediate: true },
)

// Arrow keys move between tabs, as the WAI-ARIA tabs pattern expects.
function onTabKey(event: KeyboardEvent) {
  const ids = tabs.value.map((tab) => tab.id)
  const index = ids.indexOf(active.value)
  const moves: Record<string, number> = {
    ArrowRight: index + 1,
    ArrowLeft: index - 1,
    Home: 0,
    End: ids.length - 1,
  }
  if (!(event.key in moves)) return
  event.preventDefault()
  const next = (moves[event.key] + ids.length) % ids.length
  select(ids[next])
  void nextTick(() => tabRefs.value[next]?.focus())
}
</script>

<template>
  <div class="settings">
    <header class="page-head">
      <div>
        <h1 class="page-title">Configuració</h1>
        <p class="page-lead">El hub, el full de càlcul, la lectura amb IA, el banc, les còpies i l'equip.</p>
      </div>
    </header>

    <nav class="tabs" role="tablist" aria-label="Seccions de la configuració" @keydown="onTabKey">
      <button
        v-for="tab in tabs"
        :id="`tab-${tab.id}`"
        :key="tab.id"
        ref="tabRefs"
        class="tab"
        :class="{ 'is-active': tab.id === active }"
        type="button"
        role="tab"
        :aria-selected="tab.id === active"
        :aria-controls="`panel-${tab.id}`"
        :tabindex="tab.id === active ? 0 : -1"
        @click="select(tab.id)"
      >
        <AppIcon :name="tab.icon" :size="15" />
        <span>{{ tab.label }}</span>
        <span v-if="tab.count !== undefined" class="tab-count">{{ tab.count }}</span>
        <span
          v-if="tab.dot"
          class="tab-dot"
          :class="`tab-dot-${tab.dot}`"
          :title="tab.dot === 'accent' ? 'Canvis sense desar' : 'Cal revisar-ho'"
        />
      </button>
    </nav>

    <!-- ── General ────────────────────────────────────────────────────── -->
    <div
      v-if="active === 'general'"
      id="panel-general"
      class="panel"
      role="tabpanel"
      aria-labelledby="tab-general"
    >
      <p v-if="auth.state.hub && !auth.state.hub.capabilities.llm" class="notice notice-gold">
        <AppIcon name="alert" :size="15" />
        <span>
          El hub no té cap model configurat i no podrà llegir documents. Defineix
          <code class="mono">COSECRE_OPENAI_API_KEY</code> i reinicia'l.
        </span>
      </p>

      <section class="card">
        <div class="card-head">
          <div>
            <h2 class="card-title">Servidor</h2>
            <p class="hint">El hub al qual està connectada aquesta aplicació.</p>
          </div>
          <span class="badge badge-neutral mono">{{ auth.state.hub?.version ?? '—' }}</span>
        </div>
        <dl class="facts">
          <div class="fact">
            <dt>Nom</dt>
            <dd>{{ auth.state.hub?.name ?? 'Desconegut' }}</dd>
          </div>
          <div class="fact">
            <dt>API</dt>
            <dd class="mono">v{{ auth.state.hub?.api_version }} · {{ auth.state.hub?.api_prefix }}</dd>
          </div>
          <div class="fact">
            <dt>Aplicacions</dt>
            <dd>{{ auth.state.hub?.apps.join(', ') || '—' }}</dd>
          </div>
        </dl>
      </section>

      <section class="card">
        <div class="card-head">
          <div>
            <h2 class="card-title">Capacitats</h2>
            <p class="hint">Es configuren al servidor, amb variables d'entorn.</p>
          </div>
        </div>
        <ul class="caps">
          <li v-for="cap in capabilities" :key="cap.label" class="cap">
            <span class="cap-icon" :class="{ 'is-on': cap.on }">
              <AppIcon :name="cap.icon" :size="15" />
            </span>
            <span class="cap-text">
              <strong>{{ cap.label }}</strong>
              <span class="muted">{{ cap.detail }}</span>
            </span>
            <span class="badge" :class="cap.on ? 'badge-olive' : 'badge-neutral'">
              <span class="badge-dot" />
              {{ cap.on ? 'Actiu' : 'Inactiu' }}
            </span>
          </li>
        </ul>
      </section>

      <section class="card">
        <div class="card-head">
          <div>
            <h2 class="card-title">Preferències</h2>
            <p class="hint">Només d'aquest navegador; no canvien res per a la resta de l'equip.</p>
          </div>
        </div>
        <label class="toggle">
          <input v-model="preferences.openOnCapture" type="checkbox" />
          <span class="toggle-text">
            <strong>Obre la fitxa en fer una foto o pujar un document</strong>
            <span class="hint">
              La fitxa s'obre de seguida i mostra en lila els camps que la IA està llegint. Pots omplir
              els teus alhora: es desen sols i la IA no els sobreescriu.
            </span>
          </span>
        </label>
      </section>
    </div>

    <!-- ── Spreadsheet ────────────────────────────────────────────────── -->
    <div
      v-else-if="active === 'sheet'"
      id="panel-sheet"
      class="panel"
      role="tabpanel"
      aria-labelledby="tab-sheet"
    >
      <section class="card">
        <div class="card-head">
          <div>
            <h2 class="card-title">Full de càlcul</h2>
            <p class="hint">Les credencials de Google es queden al servidor; aquí només es tria el full.</p>
          </div>
          <a
            v-if="spreadsheetHref"
            class="btn btn-outline btn-sm"
            :href="spreadsheetHref"
            target="_blank"
            rel="noopener"
          >
            <AppIcon name="external" />
            Obre el full
          </a>
        </div>

        <p v-if="settingsQuery.isLoading.value" class="empty">Carregant…</p>
        <p v-else-if="settingsQuery.isError.value" class="card-body">
          <span class="notice notice-error">
            <AppIcon name="alert" :size="15" />
            <span>{{ (settingsQuery.error.value as Error).message }}</span>
          </span>
        </p>

        <form v-else class="rows" @submit.prevent="saveMutation.mutate()">
          <div class="row">
            <div class="row-label">
              <label class="label" for="set-url">URL del full</label>
              <span class="hint">Comparteix-lo amb el compte de servei, o no s'hi podrà escriure.</span>
            </div>
            <input
              id="set-url"
              v-model="form.spreadsheet_url"
              class="input"
              type="url"
              placeholder="https://docs.google.com/spreadsheets/d/…"
            />
          </div>

          <div class="row">
            <div class="row-label">
              <label class="label" for="set-registry">Pestanya del registre</label>
              <span class="hint">Si no existeix, es crea amb les columnes, formats i desplegables.</span>
            </div>
            <input id="set-registry" v-model="form.registry_sheet_name" class="input" type="text" required />
          </div>

          <div class="row">
            <div class="row-label">
              <span class="label">Pestanyes antigues</span>
              <span class="hint">D'on llegeix la migració. No s'hi escriu res més.</span>
            </div>
            <div class="pair">
              <label class="field">
                <span class="sublabel">Factures</span>
                <input v-model="form.sheet_name" class="input" type="text" required />
              </label>
              <label class="field">
                <span class="sublabel">Tiquets</span>
                <input v-model="form.ticket_sheet_name" class="input" type="text" required />
              </label>
            </div>
          </div>

          <div class="row">
            <div class="row-label">
              <span class="label">Carpeta de Drive</span>
              <span class="hint">On es pugen els originals. Es configura al servidor.</span>
            </div>
            <div class="status-cell">
              <span
                class="badge"
                :class="settingsQuery.data.value?.drive_folder_configured ? 'badge-olive' : 'badge-gold'"
              >
                <AppIcon
                  :name="settingsQuery.data.value?.drive_folder_configured ? 'check' : 'alert'"
                  :size="12"
                />
                {{ settingsQuery.data.value?.drive_folder_configured ? 'Configurada' : 'Sense carpeta' }}
              </span>
            </div>
          </div>
        </form>
      </section>

      <MigrationPanel
        :legacy-tabs="[form.sheet_name, form.ticket_sheet_name]"
        :registry-tab="form.registry_sheet_name"
      />
    </div>

    <!-- ── AI reading ─────────────────────────────────────────────────── -->
    <div v-else-if="active === 'ai'" id="panel-ai" class="panel" role="tabpanel" aria-labelledby="tab-ai">
      <section class="card">
        <div class="card-head">
          <div>
            <h2 class="card-title">Lectura amb IA</h2>
            <p class="hint">Com es llegeixen les fotos i els PDF per omplir el registre.</p>
          </div>
          <span
            class="badge"
            :class="settingsQuery.data.value?.classifier_configured ? 'badge-olive' : 'badge-neutral'"
            title="Jev dona una segona opinió sobre el tipus de document i el pagament"
          >
            <span class="badge-dot" />
            Jev {{ settingsQuery.data.value?.classifier_configured ? 'actiu' : 'no configurat' }}
          </span>
        </div>

        <p v-if="settingsQuery.isLoading.value" class="empty">Carregant…</p>
        <form v-else class="rows" @submit.prevent="saveMutation.mutate()">
          <div class="row">
            <div class="row-label">
              <label class="label" for="set-model">Model de lectura</label>
              <span class="hint">Tria'n un de la llista o escriu-ne el nom.</span>
            </div>
            <input
              id="set-model"
              v-model="form.openai_model"
              class="input input-mono"
              type="text"
              list="cosecre-models"
              required
            />
            <datalist id="cosecre-models">
              <option v-for="model in modelOptions" :key="model" :value="model" />
            </datalist>
          </div>

          <div class="row">
            <div class="row-label">
              <label class="label" for="set-interval">Interval de consulta</label>
              <span class="hint">Cada quant es mira si hi ha documents nous (10–300 s).</span>
            </div>
            <div class="suffixed">
              <input
                id="set-interval"
                v-model.number="form.polling_interval_seconds"
                class="input"
                type="number"
                min="10"
                max="300"
              />
              <span class="suffix">segons</span>
            </div>
          </div>

          <div class="row row-stacked">
            <div class="row-label">
              <label class="label" for="set-prompt">Instruccions addicionals</label>
              <span class="hint">S'afegeixen a les de sèrie. Deixa-ho buit per no canviar res.</span>
            </div>
            <textarea
              id="set-prompt"
              v-model="form.extraction_prompt"
              class="textarea"
              rows="7"
              placeholder="Per exemple: els tiquets de benzinera sempre van al compte 628…"
            />
          </div>
        </form>
      </section>
    </div>

    <!-- ── Bank ───────────────────────────────────────────────────────── -->
    <div v-else-if="active === 'bank'" id="panel-bank" class="panel" role="tabpanel" aria-labelledby="tab-bank">
      <section class="card">
        <div class="card-head">
          <div>
            <h2 class="card-title">Extractes bancaris</h2>
            <p class="hint">
              L'IBAN del títol de cada Excel de La Caixa diu de quin compte és. Si en arriba un de
              desconegut, es pregunta un cop i es desa aquí.
            </p>
          </div>
        </div>

        <p v-if="settingsQuery.isLoading.value" class="empty">Carregant…</p>
        <form v-else class="rows" @submit.prevent="saveMutation.mutate()">
          <div class="row">
            <div class="row-label">
              <label class="label" for="set-iban-general">Compte General</label>
              <span class="hint">IBAN complet, amb o sense espais.</span>
            </div>
            <input
              id="set-iban-general"
              v-model="form.iban_general"
              class="input input-mono"
              type="text"
              placeholder="ES00 0000 0000 0000 0000 0000"
            />
          </div>
          <div class="row">
            <div class="row-label">
              <label class="label" for="set-iban-material">Material i Sortides</label>
            </div>
            <input id="set-iban-material" v-model="form.iban_material" class="input input-mono" type="text" />
          </div>
          <div class="row">
            <div class="row-label">
              <label class="label" for="set-iban-menjador">Menjador</label>
            </div>
            <input id="set-iban-menjador" v-model="form.iban_menjador" class="input input-mono" type="text" />
          </div>
          <div class="row">
            <div class="row-label">
              <label class="label" for="set-card">Targeta de prepagament</label>
              <span class="hint">El número tal com surt a l'extracte.</span>
            </div>
            <input
              id="set-card"
              v-model="form.prepaid_card_number"
              class="input input-mono"
              type="text"
              placeholder="4047 0001 …"
            />
          </div>
          <div class="row">
            <div class="row-label">
              <label class="label" for="set-caixeta">Full de la caixeta</label>
              <span class="hint">Es llegeixen les pestanyes CAIXETA'AA cada cop que algú entra a l'aplicació.</span>
            </div>
            <input
              id="set-caixeta"
              v-model="form.caixeta_spreadsheet_url"
              class="input"
              type="url"
              placeholder="https://docs.google.com/spreadsheets/d/…"
            />
          </div>
        </form>
      </section>
    </div>

    <!-- ── Backups & originals ───────────────────────────────────────── -->
    <div
      v-else-if="active === 'data'"
      id="panel-data"
      class="panel"
      role="tabpanel"
      aria-labelledby="tab-data"
    >
      <BackupsPanel />
      <OriginalsPanel />
    </div>

    <!-- ── History ────────────────────────────────────────────────────── -->
    <div
      v-else-if="active === 'history'"
      id="panel-history"
      class="panel"
      role="tabpanel"
      aria-labelledby="tab-history"
    >
      <HistoryPanel />
      <DuplicatesPanel />
    </div>

    <!-- ── Team ───────────────────────────────────────────────────────── -->
    <div
      v-else-if="active === 'team'"
      id="panel-team"
      class="panel"
      role="tabpanel"
      aria-labelledby="tab-team"
    >
      <TeamPanel />
    </div>

    <!-- ── This app (desktop updates, …) ─────────────────────────────── -->
    <div
      v-else-if="active === 'app' && platform.settingsPanel"
      id="panel-app"
      class="panel"
      role="tabpanel"
      aria-labelledby="tab-app"
    >
      <component :is="platform.settingsPanel" />
    </div>

    <!-- ── Save bar ───────────────────────────────────────────────────── -->
    <Transition name="savebar">
      <div v-if="dirty || justSaved || saveMutation.isError.value" class="savebar" role="status">
        <template v-if="saveMutation.isError.value">
          <AppIcon name="alert" :size="15" class="savebar-icon is-error" />
          <span class="savebar-text">{{ (saveMutation.error.value as Error).message }}</span>
        </template>
        <template v-else-if="dirty">
          <span class="badge-dot savebar-dot" />
          <span class="savebar-text">
            Canvis sense desar
            <span class="muted">· {{ dirtyWhere }}</span>
          </span>
        </template>
        <template v-else>
          <AppIcon name="check" :size="15" class="savebar-icon is-ok" />
          <span class="savebar-text">Configuració desada</span>
        </template>

        <div v-if="dirty" class="savebar-actions">
          <button class="btn btn-ghost btn-sm" type="button" :disabled="saveMutation.isPending.value" @click="discard">
            Descarta
          </button>
          <button
            class="btn btn-primary btn-sm"
            type="button"
            :disabled="saveMutation.isPending.value"
            @click="saveMutation.mutate()"
          >
            {{ saveMutation.isPending.value ? 'Desant…' : 'Desa els canvis' }}
          </button>
        </div>
      </div>
    </Transition>

  </div>
</template>

<style scoped>
.settings {
  display: grid;
  /* minmax(0, …): wide tables scroll inside their card, not the page. */
  grid-template-columns: minmax(0, 1fr);
  gap: 14px;
  max-width: 920px;
}

/* ── Tab bar ─────────────────────────────────────────────────────────── */
/* Sticks under the top of the page so switching section never needs a
   scroll back up; scrolls sideways on a phone instead of wrapping. */
.tabs {
  position: sticky;
  top: 0;
  z-index: 5;
  display: flex;
  gap: 2px;
  margin: 0 -2px;
  padding: 0 2px;
  overflow-x: auto;
  scrollbar-width: none;
  border-bottom: 1px solid var(--line);
  background: var(--surface-1);
}

.tabs::-webkit-scrollbar {
  display: none;
}

.tab {
  position: relative;
  display: inline-flex;
  align-items: center;
  gap: 7px;
  padding: 10px 10px 11px;
  border: 0;
  background: none;
  color: var(--ink-400);
  font: inherit;
  font-size: var(--text-base);
  font-weight: 500;
  white-space: nowrap;
  cursor: pointer;
  transition: color 0.12s ease;
}

.tab::after {
  content: '';
  position: absolute;
  left: 8px;
  right: 8px;
  bottom: -1px;
  height: 2px;
  border-radius: 2px 2px 0 0;
  background: transparent;
  transition: background-color 0.12s ease;
}

.tab:hover {
  color: var(--ink-900);
}

.tab:hover::after {
  background: var(--line-strong);
}

.tab.is-active {
  color: var(--ink-900);
}

.tab.is-active::after {
  background: var(--accent-700);
}

.tab.is-active svg {
  color: var(--accent-700);
}

.tab-count {
  min-width: 18px;
  padding: 0 5px;
  border-radius: var(--r-full);
  background: var(--surface-3);
  color: var(--ink-500);
  font-size: var(--text-xs);
  font-weight: 600;
  line-height: 17px;
  text-align: center;
}

.tab-dot {
  width: 6px;
  height: 6px;
  border-radius: var(--r-full);
}

.tab-dot-gold {
  background: var(--gold-500);
  box-shadow: 0 0 0 1px var(--gold-800) inset;
}

.tab-dot-accent {
  background: var(--accent-500);
}

/* ── Panels ──────────────────────────────────────────────────────────── */
.panel {
  display: grid;
  grid-template-columns: minmax(0, 1fr);
  gap: 14px;
  animation: panel-in 0.16s ease-out;
}

@keyframes panel-in {
  from {
    opacity: 0;
    transform: translateY(3px);
  }
}

.notice-gold {
  background: var(--gold-100);
  border-color: var(--gold-200);
  color: var(--gold-800);
}

/* Server facts: three cells in a row, divided by hairlines. */
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

/* Capabilities: a two-up list of status rows. */
.caps {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  margin: 0;
  padding: 0;
  list-style: none;
}

.cap {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 12px 16px;
  border-top: 1px solid var(--line);
}

.cap:nth-child(-n + 2) {
  border-top: 0;
}

.cap:nth-child(even) {
  border-left: 1px solid var(--line);
}

.cap-icon {
  display: grid;
  flex-shrink: 0;
  place-items: center;
  width: 28px;
  height: 28px;
  border-radius: var(--r-md);
  background: var(--surface-2);
  color: var(--ink-400);
}

.cap-icon.is-on {
  background: var(--olive-100);
  color: var(--olive-700);
}

.cap-text {
  display: grid;
  flex: 1;
  min-width: 0;
  line-height: 1.35;
  font-size: var(--text-base);
}

.cap-text .muted {
  font-size: var(--text-sm);
}

/* Setting rows: label and hint on the left, the control on the right. */
.rows {
  display: grid;
}

.row {
  display: grid;
  grid-template-columns: minmax(0, 240px) minmax(0, 1fr);
  align-items: start;
  gap: 6px 28px;
  padding: 14px 16px;
}

.row + .row {
  border-top: 1px solid var(--line);
}

.row-stacked {
  grid-template-columns: minmax(0, 1fr);
}

.row-label {
  display: grid;
  gap: 2px;
  padding-top: 6px;
}

.row-stacked .row-label {
  padding-top: 0;
}

.row-label .label {
  color: var(--ink-700);
  font-size: var(--text-base);
  font-weight: 600;
  letter-spacing: 0;
  text-transform: none;
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

.status-cell {
  padding-top: 6px;
}

.suffixed {
  display: flex;
  align-items: center;
  gap: 8px;
  max-width: 180px;
}

.suffix {
  color: var(--ink-400);
  font-size: var(--text-base);
}

/* Browser preference: one checkbox row. */
.toggle {
  display: flex;
  align-items: flex-start;
  gap: 10px;
  padding: 14px 16px;
  cursor: pointer;
}

.toggle input {
  margin-top: 3px;
  accent-color: var(--accent-700);
}

.toggle-text {
  display: grid;
  gap: 2px;
  font-size: var(--text-base);
}

.toggle-text strong {
  color: var(--ink-700);
  font-weight: 600;
}

code {
  padding: 1px 4px;
  border-radius: var(--r-xs);
  background: var(--surface-2);
}

/* ── Save bar ────────────────────────────────────────────────────────── */
/* Floats over the bottom of the page instead of taking a row of it. */
.savebar {
  position: sticky;
  bottom: 16px;
  z-index: 6;
  display: flex;
  align-items: center;
  gap: 10px;
  justify-self: center;
  width: min(100%, 560px);
  min-height: 44px;
  padding: 6px 6px 6px 14px;
  border: 1px solid var(--line-strong);
  border-radius: var(--r-lg);
  background: var(--surface-0);
  box-shadow: var(--shadow-lg);
  font-size: var(--text-base);
}

.savebar-dot {
  width: 7px;
  height: 7px;
  color: var(--accent-500);
}

.savebar-icon.is-ok {
  color: var(--olive-700);
}

.savebar-icon.is-error {
  color: var(--danger-700);
}

.savebar-text {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  color: var(--ink-700);
  font-weight: 500;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.savebar-text .muted {
  font-weight: 400;
}

.savebar-actions {
  display: flex;
  gap: 4px;
}

.savebar-enter-active,
.savebar-leave-active {
  transition:
    opacity 0.16s ease,
    transform 0.16s ease;
}

.savebar-enter-from,
.savebar-leave-to {
  opacity: 0;
  transform: translateY(8px);
}

@media (max-width: 860px) {
  .tabs {
    top: var(--topbar-h);
  }
}

@media (max-width: 720px) {
  .facts,
  .caps {
    grid-template-columns: minmax(0, 1fr);
  }

  .fact + .fact {
    border-left: 0;
    border-top: 1px solid var(--line);
  }

  .cap:nth-child(2) {
    border-top: 1px solid var(--line);
  }

  .cap:nth-child(even) {
    border-left: 0;
  }

  .row {
    grid-template-columns: minmax(0, 1fr);
  }

  .row-label {
    padding-top: 0;
  }

  .savebar-text .muted {
    display: none;
  }
}

@media (prefers-reduced-motion: reduce) {
  .panel {
    animation: none;
  }
}
</style>
