<script setup lang="ts">
import { computed, ref } from 'vue'
import { useMutation, useQuery, useQueryClient } from '@tanstack/vue-query'
import { RouterLink } from 'vue-router'

import { api, ApiError } from '../api/client'
import type { Categoria, MirrorStatus, Movement, Statement } from '../api/types'
import { METODES_PAGAMENT, formatAmount, formatDate } from '../document-fields'
import { CATEGORIA_LABEL, SOURCE_LABEL } from '../matching'
import AppIcon from '../components/AppIcon.vue'
import DocumentCard from '../components/DocumentCard.vue'
import { useDocumentCards } from '../composables/useDocumentCards'

/**
 * Bringing statements in — and only that. Matching them to invoices is a task
 * of its own (Tasques → Justificar extractes), so nothing here proposes,
 * confirms or colours anything by confidence.
 */
const queryClient = useQueryClient()

const ACCOUNTS = ['General', 'Material i Sortides', 'Menjador'] as const
const SOURCES = [
  { compte: 'General', format: 'Excel La Caixa' },
  { compte: 'Material i Sortides', format: 'Excel La Caixa' },
  { compte: 'Menjador', format: 'Excel La Caixa' },
  { compte: 'Targeta Prepagament', format: 'PDF de la targeta' },
  { compte: 'Caixeta', format: 'Full de càlcul' },
]

const statementsQuery = useQuery({ queryKey: ['statements'], queryFn: api.listStatements })
// The register entry a line paid, floating beside it on request.
const documentCards = useDocumentCards()
const statements = computed<Statement[]>(() => statementsQuery.data.value ?? [])

const caixetaQuery = useQuery({
  queryKey: ['caixeta'],
  queryFn: api.caixetaStatus,
  refetchInterval: (query) => (query.state.data?.running ? 2000 : 60000),
})

function refresh() {
  void queryClient.invalidateQueries({ queryKey: ['statements'] })
  void queryClient.invalidateQueries({ queryKey: ['statement-movements'] })
  void queryClient.invalidateQueries({ queryKey: ['reconcile-statements'] })
}

/** Per source: how many statements, and up to when. */
const coverage = computed(() =>
  SOURCES.map((source) => {
    const own = statements.value.filter((s) => s.compte === source.compte)
    const until = own.map((s) => s.period_to).filter(Boolean).sort().at(-1) ?? null
    return { ...source, count: own.length, until, movements: own.reduce((n, s) => n + s.rows_total, 0) }
  }),
)

// ── The dropzone ─────────────────────────────────────────────────────────────

type Drop = {
  id: string
  file: File
  state: 'reading' | 'done' | 'needs_account' | 'error'
  message: string
  iban?: string
  statement?: Statement
}

const drops = ref<Drop[]>([])
const dragging = ref(false)

function patch(id: string, values: Partial<Drop>) {
  drops.value = drops.value.map((d) => (d.id === id ? { ...d, ...values } : d))
}

async function send(drop: Drop, compte?: string) {
  patch(drop.id, {
    state: 'reading',
    message: drop.file.name.toLowerCase().endsWith('.pdf')
      ? 'gpt-6-luna està llegint el PDF…'
      : 'Comprovant el format amb gpt-6-luna i llegint els moviments…',
  })
  try {
    const statement = await api.uploadStatement(drop.file, compte)
    patch(drop.id, {
      state: 'done',
      statement,
      message: `${statement.rows_total} moviments · ${statement.rows_new} nous · ${statement.rows_duplicate} ja hi eren`,
    })
    refresh()
  } catch (error) {
    const data = error instanceof ApiError ? (error.data as { code?: string; iban?: string; message?: string }) : null
    if (data?.code === 'needs_account') {
      patch(drop.id, { state: 'needs_account', iban: data.iban, message: data.message ?? '' })
    } else {
      patch(drop.id, { state: 'error', message: error instanceof Error ? error.message : String(error) })
    }
  }
}

function accept(files: FileList | File[] | null) {
  for (const file of Array.from(files ?? [])) {
    const drop: Drop = { id: crypto.randomUUID(), file, state: 'reading', message: '' }
    drops.value = [drop, ...drops.value]
    void send(drop)
  }
}

function onDrop(event: DragEvent) {
  dragging.value = false
  accept(event.dataTransfer?.files ?? null)
}

function onPick(event: Event) {
  const input = event.target as HTMLInputElement
  accept(input.files)
  input.value = ''
}

function dismiss(id: string) {
  drops.value = drops.value.filter((d) => d.id !== id)
}

// ── The accounting spreadsheet ───────────────────────────────────────────────
// Every account has a tab there. The button brings in what people typed in its
// invoice columns, then rewrites the tabs from here.

const mirrorQuery = useQuery({ queryKey: ['statements-mirror'], queryFn: api.mirrorStatus })
const mirrorResult = ref<MirrorStatus | null>(null)
const mirrorSync = useMutation({
  mutationFn: api.syncMirror,
  onSuccess: (status) => {
    queryClient.setQueryData(['statements-mirror'], status)
    mirrorResult.value = status
    if (status.applied.length) {
      refresh()
      void queryClient.invalidateQueries({ queryKey: ['reconcile-statements'] })
    }
  },
})
const mirrorError = computed(() => {
  const error = mirrorSync.error.value
  return error instanceof ApiError ? error.message : error ? String(error) : mirrorQuery.data.value?.error
})

// ── Caixeta ──────────────────────────────────────────────────────────────────

const caixetaSync = useMutation({
  mutationFn: () => api.syncCaixeta(false),
  onSuccess: (status) => {
    queryClient.setQueryData(['caixeta'], status)
    refresh()
  },
})

function ago(iso: string | null | undefined) {
  if (!iso) return 'mai'
  // SQLite drops the zone; the hub stores UTC, so a bare timestamp is UTC.
  const utc = /[zZ]|[+-]\d\d:?\d\d$/.test(iso) ? iso : `${iso}Z`
  const minutes = Math.round((Date.now() - new Date(utc).getTime()) / 60000)
  if (minutes < 1) return 'fa un moment'
  if (minutes < 60) return `fa ${minutes} min`
  const hours = Math.round(minutes / 60)
  if (hours < 24) return `fa ${hours} h`
  return formatDate(iso.slice(0, 10))
}

// ── Statements and their movements ───────────────────────────────────────────

const open = ref<number | null>(null)
const movementsQuery = useQuery({
  queryKey: computed(() => ['statement-movements', open.value]),
  queryFn: () => api.statementMovements(open.value as number),
  enabled: computed(() => open.value !== null),
})

function toggle(statement: Statement) {
  open.value = open.value === statement.id ? null : statement.id
}

const updateMovement = useMutation({
  mutationFn: ({ id, payload }: { id: number; payload: { tipus?: string; categoria?: Categoria } }) =>
    api.updateMovement(id, payload),
  onSuccess: refresh,
})

const pendingDelete = ref<Statement | null>(null)
const deleteError = ref('')
const deleteStatement = useMutation({
  mutationFn: (id: number) => api.deleteStatement(id),
  onSuccess: () => {
    pendingDelete.value = null
    open.value = null
    refresh()
  },
  onError: (error) => {
    deleteError.value = error instanceof Error ? error.message : String(error)
  },
})

function period(s: Statement) {
  if (!s.period_from) return '—'
  return s.period_from === s.period_to
    ? formatDate(s.period_from)
    : `${formatDate(s.period_from)} – ${formatDate(s.period_to)}`
}

const CATEGORIES = Object.entries(CATEGORIA_LABEL) as [Categoria, string][]

function amountClass(m: Movement) {
  return m.import_value > 0 ? 'in' : ''
}
</script>

<template>
  <div class="statements">
    <header class="page-head">
      <div>
        <h1 class="page-title">Extractes bancaris</h1>
        <p class="page-lead">
          Els moviments dels tres comptes, de la targeta de prepagament i de la caixeta, desats al
          servidor. Per relacionar-los amb factures, ves a
          <RouterLink :to="{ name: 'reconcile' }">Justificar extractes</RouterLink>.
        </p>
      </div>
      <div v-if="mirrorQuery.data.value?.configured" class="head-actions">
        <a
          v-if="mirrorQuery.data.value.spreadsheet_url"
          class="btn btn-ghost"
          :href="mirrorQuery.data.value.spreadsheet_url"
          target="_blank"
          rel="noopener"
        >
          <AppIcon name="external" />
          Obre el full
        </a>
        <button
          class="btn btn-outline"
          type="button"
          :disabled="mirrorSync.isPending.value || mirrorQuery.data.value.running"
          :title="`Porta a Cosecre les factures escrites a les pestanyes «Extracte …» del full de comptabilitat, i torna a escriure-les. Última: ${ago(mirrorQuery.data.value.synced_at)}.`"
          @click="mirrorSync.mutate()"
        >
          <AppIcon name="sheet" :class="{ spin: mirrorSync.isPending.value }" />
          {{ mirrorSync.isPending.value ? 'Sincronitzant…' : 'Sincronitza amb el full' }}
        </button>
      </div>
    </header>

    <p v-if="mirrorError" class="notice notice-error">
      <AppIcon name="alert" :size="15" />
      <span>{{ mirrorError }}</span>
    </p>
    <section v-else-if="mirrorResult" class="card mirror-result">
      <div class="card-head">
        <h2 class="card-title">
          <AppIcon name="check" :size="14" class="ok" />
          Full sincronitzat
        </h2>
        <span class="muted">
          {{ mirrorResult.applied.length ? `${mirrorResult.applied.length} canvis del full aplicats` : 'Cap canvi al full' }}
          · {{ mirrorResult.tabs.length }} pestanyes reescrites
        </span>
        <button class="btn btn-ghost btn-icon btn-sm" type="button" title="Amaga" @click="mirrorResult = null">
          <AppIcon name="close" :size="14" />
        </button>
      </div>
      <ul v-if="mirrorResult.applied.length || mirrorResult.issues.length" class="mirror-lines">
        <li v-for="line in mirrorResult.applied" :key="`a-${line.compte}-${line.codi}`">
          <span class="mono">{{ line.codi }}</span>
          <span class="muted">{{ line.compte }}</span>
          <span>{{ line.text }}</span>
        </li>
        <li v-for="line in mirrorResult.issues" :key="`i-${line.compte}-${line.codi}`" class="issue">
          <span class="mono">{{ line.codi }}</span>
          <span class="muted">{{ line.compte }}</span>
          <span>{{ line.text }} <span class="muted">— al full hi torna a haver el que diu Cosecre.</span></span>
        </li>
      </ul>
    </section>

    <section class="sources" aria-label="Fonts">
      <article v-for="source in coverage" :key="source.compte" class="source">
        <span class="source-name">{{ source.compte }}</span>
        <span class="source-format muted">{{ source.format }}</span>
        <span class="source-state">
          <template v-if="source.count">
            {{ source.movements }} moviments<template v-if="source.until"> · fins al {{ formatDate(source.until) }}</template>
          </template>
          <span v-else class="muted">Encara cap extracte</span>
        </span>
      </article>
    </section>

    <section class="card intake">
      <label
        class="dropzone"
        :class="{ active: dragging }"
        @dragover.prevent="dragging = true"
        @dragleave.prevent="dragging = false"
        @drop.prevent="onDrop"
      >
        <input type="file" accept=".xls,.xlsx,application/pdf" multiple @change="onPick" />
        <AppIcon name="upload" :size="22" />
        <span class="dropzone-title">Arrossega aquí l'Excel de La Caixa o el PDF de la targeta</span>
        <span class="muted dropzone-sub">
          El tipus es detecta sol. L'Excel el revisa gpt-6-luna abans de llegir-lo; el PDF el llegeix gpt-6-luna.
        </span>
        <span class="btn btn-outline btn-sm">Tria fitxers</span>
      </label>

      <ul v-if="drops.length" class="drops">
        <li v-for="drop in drops" :key="drop.id" class="drop" :class="drop.state">
          <AppIcon
            :name="drop.state === 'done' ? 'check' : drop.state === 'error' ? 'alert' : drop.state === 'needs_account' ? 'bank' : 'refresh'"
            :size="15"
            :class="{ spin: drop.state === 'reading' }"
          />
          <div class="drop-body">
            <strong class="truncate">{{ drop.file.name }}</strong>
            <span class="drop-message">{{ drop.message }}</span>
            <ul v-if="drop.statement?.warnings.length" class="warnings">
              <li v-for="warning in drop.statement.warnings" :key="warning">{{ warning }}</li>
            </ul>
            <div v-if="drop.state === 'needs_account'" class="account-pick">
              <button
                v-for="account in ACCOUNTS"
                :key="account"
                class="btn btn-outline btn-sm"
                type="button"
                @click="send(drop, account)"
              >
                {{ account }}
              </button>
            </div>
          </div>
          <RouterLink
            v-if="drop.state === 'done' && drop.statement"
            class="btn btn-sm btn-primary"
            :to="{ name: 'reconcile', query: { extracte: drop.statement.id } }"
          >
            Justifica'l
            <AppIcon name="chevron" :size="13" />
          </RouterLink>
          <button
            v-if="drop.state !== 'reading'"
            class="btn btn-ghost btn-icon btn-sm"
            type="button"
            title="Amaga"
            @click="dismiss(drop.id)"
          >
            <AppIcon name="close" :size="14" />
          </button>
        </li>
      </ul>

      <div class="caixeta" :class="{ bad: caixetaQuery.data.value?.error }">
        <AppIcon name="sheet" :size="15" />
        <span v-if="!caixetaQuery.data.value?.configured" class="muted">
          La caixeta no està configurada (Configuració → Extractes bancaris).
        </span>
        <span v-else-if="caixetaQuery.data.value?.error">{{ caixetaQuery.data.value.error }}</span>
        <span v-else>
          Caixeta sincronitzada {{ ago(caixetaQuery.data.value?.synced_at) }}.
          <span class="muted">Es torna a llegir cada cop que algú entra a l'aplicació.</span>
        </span>
        <button
          v-if="caixetaQuery.data.value?.configured"
          class="btn btn-ghost btn-sm"
          type="button"
          :disabled="caixetaSync.isPending.value || caixetaQuery.data.value?.running"
          @click="caixetaSync.mutate()"
        >
          <AppIcon name="refresh" :size="13" :class="{ spin: caixetaSync.isPending.value }" />
          Sincronitza
        </button>
      </div>
    </section>

    <section class="card">
      <div class="card-head">
        <h2 class="card-title">Extractes desats</h2>
        <span class="muted count">{{ statements.length }}</span>
      </div>
      <p v-if="statementsQuery.isLoading.value" class="empty">Carregant…</p>
      <p v-else-if="!statements.length" class="empty">Encara no s'ha desat cap extracte.</p>
      <div v-else class="table-scroll">
        <table class="table">
          <thead>
            <tr>
              <th class="caret-col"><span class="sr-only">Obre</span></th>
              <th>Compte</th>
              <th>Font</th>
              <th>Període</th>
              <th class="num">Moviments</th>
              <th>Pujat per</th>
              <th>Data</th>
              <th class="actions"><span class="sr-only">Accions</span></th>
            </tr>
          </thead>
          <tbody>
            <template v-for="statement in statements" :key="statement.id">
              <tr class="row" :class="{ open: open === statement.id }" @click="toggle(statement)">
                <td class="caret-col">
                  <AppIcon name="chevron" :size="13" class="caret" />
                </td>
                <td><strong>{{ statement.compte }}</strong></td>
                <td>
                  {{ SOURCE_LABEL[statement.source] }}
                  <span class="sub muted truncate" :title="statement.file_name">{{ statement.file_name }}</span>
                </td>
                <td class="mono">{{ period(statement) }}</td>
                <td class="num">{{ statement.rows_total }}</td>
                <td class="muted">{{ statement.created_by || '—' }}</td>
                <td class="mono">{{ formatDate(statement.updated_at.slice(0, 10)) }}</td>
                <td class="actions" @click.stop>
                  <div class="row-actions">
                    <RouterLink
                      class="btn btn-ghost btn-sm"
                      :to="{ name: 'reconcile', query: { extracte: statement.id } }"
                    >
                      Justifica
                    </RouterLink>
                    <button
                      v-if="statement.has_file"
                      class="btn btn-ghost btn-icon btn-sm"
                      type="button"
                      title="Descarrega l'original"
                      @click="api.downloadStatement(statement)"
                    >
                      <AppIcon name="download" />
                    </button>
                    <button
                      v-if="statement.source !== 'caixeta_sheet'"
                      class="btn btn-ghost btn-icon btn-sm delete"
                      type="button"
                      title="Esborra l'extracte"
                      @click="
                        () => {
                          deleteError = ''
                          pendingDelete = statement
                        }
                      "
                    >
                      <AppIcon name="trash" />
                    </button>
                  </div>
                </td>
              </tr>
              <tr v-if="open === statement.id" class="movements-row">
                <td colspan="8">
                  <p v-if="movementsQuery.isLoading.value" class="empty">Carregant moviments…</p>
                  <table v-else class="table inner">
                    <thead>
                      <tr>
                        <th>Data</th>
                        <th>Concepte</th>
                        <th>Més dades</th>
                        <th class="num">Import</th>
                        <th class="num">Saldo</th>
                        <th>Registre</th>
                        <th>Tipus</th>
                        <th>Categoria</th>
                      </tr>
                    </thead>
                    <tbody>
                      <tr v-for="m in movementsQuery.data.value ?? []" :key="m.id" :class="{ dim: m.categoria !== 'pagament' }">
                        <td class="mono">{{ formatDate(m.data) }}</td>
                        <td class="concept">
                          <span class="truncate">{{ m.concepte }}</span>
                          <span v-if="m.codi || m.external_ref" class="muted ref-tag">{{ m.codi || m.external_ref }}</span>
                        </td>
                        <td class="truncate extra">{{ m.mes_dades || '—' }}</td>
                        <td class="num" :class="amountClass(m)">{{ formatAmount(m.import_value) }}</td>
                        <td class="num muted">{{ m.saldo == null ? '' : formatAmount(m.saldo) }}</td>
                        <td class="registre">
                          <button
                            v-for="doc in m.matched"
                            :key="doc.num_doc_intern"
                            class="reg-chip"
                            :class="{ on: documentCards.isOpen(doc.num_doc_intern) }"
                            type="button"
                            :title="`Mostra ${doc.num_factura || doc.num_doc_intern} del registre`"
                            @click="documentCards.toggle(doc.num_doc_intern, $event)"
                          >
                            <AppIcon name="invoice" :size="12" />
                            <span class="truncate">{{ doc.num_factura || 'Sense número' }}<span class="reg-who"> · {{ doc.proveidor }}</span></span>
                          </button>
                          <span v-if="!m.matched.length" class="muted">{{ m.categoria === 'pagament' ? (m.match_status === 'rejected' ? 'Sense factura' : '—') : '' }}</span>
                        </td>
                        <td>
                          <select
                            class="select select-sm"
                            :value="m.tipus"
                            aria-label="Tipus de pagament"
                            @change="updateMovement.mutate({ id: m.id, payload: { tipus: ($event.target as HTMLSelectElement).value } })"
                          >
                            <option value="">—</option>
                            <option v-for="option in METODES_PAGAMENT" :key="option" :value="option">{{ option }}</option>
                          </select>
                        </td>
                        <td>
                          <select
                            class="select select-sm"
                            :value="m.categoria"
                            :disabled="m.match_status === 'confirmed'"
                            aria-label="Categoria"
                            @change="updateMovement.mutate({ id: m.id, payload: { categoria: ($event.target as HTMLSelectElement).value as Categoria } })"
                          >
                            <option v-for="[value, label] in CATEGORIES" :key="value" :value="value">{{ label }}</option>
                          </select>
                        </td>
                      </tr>
                    </tbody>
                  </table>
                </td>
              </tr>
            </template>
          </tbody>
        </table>
      </div>
    </section>

    <DocumentCard
      v-for="card in documentCards.cards.value"
      :key="card.reference"
      :reference="card.reference"
      :x="card.x"
      :y="card.y"
      @close="documentCards.close(card)"
      @move="(x, y) => Object.assign(card, { x, y })"
    />

    <Teleport to="body">
      <div v-if="pendingDelete" class="overlay" @click.self="pendingDelete = null">
        <div class="dialog" role="dialog" aria-modal="true">
          <h2 class="dialog-title">Vols esborrar aquest extracte?</h2>
          <p class="subtle">
            S'esborraran els {{ pendingDelete.rows_total }} moviments de
            <strong>{{ pendingDelete.file_name }}</strong> i les propostes fetes per a ells. Les factures
            del registre no es toquen.
          </p>
          <p v-if="deleteError" class="notice notice-error">
            <AppIcon name="alert" :size="15" />
            <span>{{ deleteError }}</span>
          </p>
          <div class="dialog-actions">
            <button class="btn btn-outline" type="button" @click="pendingDelete = null">Cancel·la</button>
            <button
              class="btn btn-danger"
              type="button"
              :disabled="deleteStatement.isPending.value"
              @click="deleteStatement.mutate(pendingDelete.id)"
            >
              Esborra
            </button>
          </div>
        </div>
      </div>
    </Teleport>
  </div>
</template>

<style scoped>
.statements {
  display: grid;
  grid-template-columns: minmax(0, 1fr);
  gap: 16px;
  max-width: 1280px;
}

.sources {
  display: grid;
  grid-template-columns: repeat(5, minmax(0, 1fr));
  gap: 8px;
}

.source {
  display: grid;
  gap: 2px;
  padding: 10px 12px;
  background: var(--surface-0);
  border: 1px solid var(--line);
  border-radius: var(--r-lg);
  box-shadow: var(--shadow-xs);
}

.source-name {
  font-weight: 600;
}

.source-format {
  font-size: var(--text-xs);
  letter-spacing: 0.04em;
  text-transform: uppercase;
}

.source-state {
  font-size: var(--text-sm);
  font-variant-numeric: tabular-nums;
}

.intake {
  display: grid;
  gap: 12px;
  padding: 14px;
}

.dropzone {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 6px;
  min-height: 120px;
  padding: 16px;
  text-align: center;
  cursor: pointer;
  border: 1px dashed var(--line-strong);
  border-radius: var(--r-md);
  background: var(--surface-1);
  color: var(--ink-500);
  transition:
    border-color 0.12s ease,
    background-color 0.12s ease;
}

.dropzone input {
  display: none;
}

.dropzone:hover,
.dropzone.active {
  border-color: var(--accent-500);
  background: var(--accent-100);
  color: var(--accent-700);
}

.dropzone-title {
  font-size: var(--text-base);
  font-weight: 500;
  color: var(--ink-700);
}

.dropzone-sub {
  font-size: var(--text-sm);
}

.drops {
  display: grid;
  gap: 6px;
  margin: 0;
  padding: 0;
  list-style: none;
}

.drop {
  display: flex;
  align-items: flex-start;
  gap: 10px;
  padding: 8px 10px;
  border: 1px solid var(--line);
  border-radius: var(--r-md);
  background: var(--surface-0);
}

.drop > :first-child {
  margin-top: 2px;
}

.drop.done > :first-child {
  color: var(--olive-700);
}

.drop.error {
  border-color: var(--danger-200);
  background: var(--danger-100);
}

.drop.error > :first-child {
  color: var(--danger-700);
}

.drop.needs_account {
  border-color: var(--gold-200);
  background: var(--gold-100);
}

.drop-body {
  display: grid;
  gap: 2px;
  flex: 1;
  min-width: 0;
}

.drop-message {
  font-size: var(--text-sm);
  color: var(--ink-500);
}

.warnings {
  margin: 4px 0 0;
  padding-left: 16px;
  font-size: var(--text-sm);
  color: var(--gold-800);
}

.account-pick {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-top: 6px;
}

.head-actions {
  display: flex;
  gap: 8px;
}

.mirror-result .card-head {
  align-items: center;
  justify-content: flex-start;
}

.mirror-result .card-head .btn {
  margin-left: auto;
}

.mirror-result .card-title {
  display: inline-flex;
  align-items: center;
  gap: 6px;
}

.mirror-result .ok {
  color: var(--olive-700);
}

.mirror-lines {
  display: grid;
  gap: 4px;
  margin: 0;
  padding: 10px 16px 12px;
  list-style: none;
  font-size: var(--text-sm);
}

.mirror-lines li {
  display: grid;
  grid-template-columns: 64px 140px 1fr;
  gap: 10px;
}

.mirror-lines .issue {
  color: var(--danger-700);
}

.caixeta {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: var(--text-sm);
  color: var(--ink-700);
}

.caixeta > :first-child {
  color: var(--olive-700);
}

.caixeta.bad,
.caixeta.bad > :first-child {
  color: var(--danger-700);
}

.caixeta .btn {
  margin-left: auto;
}

.count {
  font-variant-numeric: tabular-nums;
}

.row {
  cursor: pointer;
}

.caret-col {
  width: 28px;
}

.caret {
  color: var(--ink-400);
  transition: transform 0.12s ease;
}

.row.open .caret {
  transform: rotate(90deg);
}

.sub {
  display: block;
  max-width: 260px;
  font-size: var(--text-xs);
}

.row-actions {
  display: inline-flex;
  align-items: center;
  gap: 4px;
}

.delete:hover:not(:disabled) {
  background: var(--danger-100);
  color: var(--danger-700);
}

.registre {
  max-width: 220px;
}

.reg-chip {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  max-width: 100%;
  padding: 1px 7px;
  border: 1px solid var(--accent-200);
  border-left: 3px solid var(--accent-700);
  border-radius: var(--r-sm);
  background: var(--accent-50);
  color: var(--ink-900);
  font-size: var(--text-xs);
  cursor: pointer;
}

.reg-chip:hover,
.reg-chip.on {
  border-color: var(--accent-500);
  border-left-color: var(--accent-700);
}

.reg-chip .reg-who {
  color: var(--ink-500);
}

.movements-row > td {
  padding: 0 0 8px 28px;
  background: var(--surface-1);
}

.inner {
  font-size: var(--text-sm);
}

.inner td {
  padding-top: 4px;
  padding-bottom: 4px;
}

.inner tr.dim td {
  color: var(--ink-400);
}

.concept {
  max-width: 220px;
}

.concept .truncate {
  display: block;
}

.ref-tag {
  font-family: var(--font-mono);
  font-size: var(--text-xs);
}

.extra {
  max-width: 220px;
}

.num.in {
  color: var(--olive-700);
}

.select-sm {
  height: 26px;
  padding: 0 6px;
  font-size: var(--text-xs);
  width: auto;
  max-width: 170px;
}

.spin {
  animation: spin 0.9s linear infinite;
}

@keyframes spin {
  to {
    transform: rotate(360deg);
  }
}

@media (max-width: 960px) {
  .sources {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}
</style>
