<script setup lang="ts">
import { computed, nextTick, ref, watch } from 'vue'
import { useMutation, useQuery, useQueryClient } from '@tanstack/vue-query'

import { api } from '../../api/client'
import type { Partida, PressupostImportSummary } from '../../api/types'
import { formatEuros, fundTone, matches, searchText } from '../../partides'
import AppIcon from '../AppIcon.vue'

/**
 * Configuració → Dades del centre → Pressupost.
 *
 * Where the year's budget lines come in (esfer@'s Excel, read and previewed
 * before anything is written), and where the secretari/a tells Jev what the
 * lines are for: once in general, and line by line where the name is not
 * enough. Both are read every time Jev proposes a line.
 */
const queryClient = useQueryClient()
const exercici = ref<number | null>(null)
const budgetQuery = useQuery({
  queryKey: computed(() => ['pressupost', exercici.value]),
  queryFn: () => api.getPressupost(exercici.value),
})
const budget = computed(() => budgetQuery.data.value)

function refresh() {
  void queryClient.invalidateQueries({ queryKey: ['pressupost'] })
  void queryClient.invalidateQueries({ queryKey: ['partides-queue'] })
}

// ── Import ──────────────────────────────────────────────────────────────────

const fileInput = ref<HTMLInputElement | null>(null)
const picked = ref<File | null>(null)
const preview = ref<PressupostImportSummary | null>(null)
const imported = ref<PressupostImportSummary | null>(null)
const dragging = ref(false)

const previewMutation = useMutation({
  mutationFn: (file: File) => api.importPressupost(file, true),
  onSuccess: (summary) => (preview.value = summary),
})

const importMutation = useMutation({
  mutationFn: (file: File) => api.importPressupost(file, false),
  onSuccess: (summary) => {
    imported.value = summary
    preview.value = null
    picked.value = null
    exercici.value = summary.exercici
    refresh()
  },
})

function choose(file: File | undefined | null) {
  if (!file) return
  picked.value = file
  preview.value = null
  imported.value = null
  importMutation.reset()
  previewMutation.mutate(file)
}

function onDrop(event: DragEvent) {
  dragging.value = false
  choose(event.dataTransfer?.files?.[0])
}

function cancel() {
  picked.value = null
  preview.value = null
  previewMutation.reset()
  if (fileInput.value) fileInput.value.value = ''
}

const importedAt = computed(() =>
  budget.value?.imported_at
    ? new Date(budget.value.imported_at).toLocaleString('ca-ES', { dateStyle: 'medium', timeStyle: 'short' })
    : '',
)

// ── General context ─────────────────────────────────────────────────────────

const general = ref('')
const generalSaved = ref('')
watch(
  () => budget.value?.context_general,
  (value) => {
    if (value === undefined || general.value !== generalSaved.value) return
    general.value = value
    generalSaved.value = value
  },
  { immediate: true },
)

const generalMutation = useMutation({
  mutationFn: () => api.updatePartidesContext(general.value, exercici.value),
  onSuccess: (data) => {
    generalSaved.value = data.context_general
    general.value = data.context_general
    queryClient.setQueryData(['pressupost', exercici.value], data)
  },
})

// ── Context per line ────────────────────────────────────────────────────────

const query = ref('')
const onlyWithContext = ref(false)
const withIncome = ref(false)
const editing = ref<number | null>(null)
const editText = ref('')

const byCode = computed(() => new Map((budget.value?.partides ?? []).map((p) => [p.codi, p])))

const rows = computed(() => {
  const all = (budget.value?.partides ?? []).filter((p) => withIncome.value || p.tipus === 'despesa')
  const leaves = all.filter(
    (p) =>
      !p.te_fills &&
      (!onlyWithContext.value || p.context) &&
      (!query.value || matches(searchText(p, p.codi_pare ? byCode.value.get(p.codi_pare) : undefined), query.value)),
  )
  // Headings stay as dividers above the lines they hold.
  const keep = new Set(leaves.map((p) => p.codi_pare).filter(Boolean))
  return all.filter((p) => (p.te_fills ? keep.has(p.codi) : leaves.includes(p)))
})

const withContext = computed(() => (budget.value?.partides ?? []).filter((p) => p.context).length)

function edit(p: Partida) {
  editing.value = p.id
  editText.value = p.context
  void nextTick(() => document.getElementById(`context-${p.id}`)?.focus())
}

const lineMutation = useMutation({
  mutationFn: ({ id, context }: { id: number; context: string }) => api.updatePartidaContext(id, context),
  onSuccess: (line) => {
    queryClient.setQueryData(['pressupost', exercici.value], (data: typeof budget.value) =>
      data ? { ...data, partides: data.partides.map((p) => (p.id === line.id ? line : p)) } : data,
    )
    editing.value = null
  },
})

function saveLine(p: Partida) {
  lineMutation.mutate({ id: p.id, context: editText.value })
}

</script>

<template>
  <section class="card">
    <div class="card-head">
      <div>
        <h2 class="card-title">Pressupost d'esfer@</h2>
        <p class="hint">Les partides on s'imputen els moviments dels extractes. Cada curs, torna a importar l'Excel: el que ja s'ha assignat i escrit es manté.</p>
      </div>
      <select
        v-if="(budget?.exercicis.length ?? 0) > 1"
        v-model="exercici"
        class="select select-sm"
        aria-label="Exercici"
      >
        <option :value="null">Darrer exercici</option>
        <option v-for="year in budget?.exercicis" :key="year" :value="year">{{ year }}</option>
      </select>
    </div>

    <dl v-if="budget?.exercici" class="facts">
      <div class="fact">
        <dt>Exercici</dt>
        <dd class="mono">{{ budget.exercici }}</dd>
      </div>
      <div class="fact">
        <dt>Centre</dt>
        <dd>{{ budget.centre }} <span class="mono subtle">{{ budget.codi_centre }}</span></dd>
      </div>
      <div class="fact">
        <dt>NIF</dt>
        <dd class="mono">{{ budget.nif || '—' }}</dd>
      </div>
      <div class="fact">
        <dt>Partides</dt>
        <dd>
          {{ budget.partides.filter((p) => p.tipus === 'despesa' && !p.te_fills).length }} de despesa ·
          {{ formatEuros(budget.total_despeses) }}
        </dd>
      </div>
      <div class="fact">
        <dt>Importat</dt>
        <dd>{{ importedAt }} <span v-if="budget.data_informe" class="subtle">· informe del {{ budget.data_informe }}</span></dd>
      </div>
    </dl>

    <div class="import">
      <div class="where">
        <span class="where-label">On es troba</span>
        <ol class="crumbs">
          <li>esfer@</li>
          <li>Informes i extraccions</li>
          <li>Consulta les dades del pressupost</li>
          <li><AppIcon name="download" :size="12" /> Exporta XLS</li>
        </ol>
      </div>

      <label
        v-if="!preview"
        class="drop"
        :class="{ 'is-over': dragging, 'is-busy': previewMutation.isPending.value }"
        @dragover.prevent="dragging = true"
        @dragleave="dragging = false"
        @drop.prevent="onDrop"
      >
        <input
          ref="fileInput"
          type="file"
          accept=".xls,.xlsx,application/vnd.ms-excel,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
          class="sr-only"
          @change="choose(($event.target as HTMLInputElement).files?.[0])"
        />
        <AppIcon :name="previewMutation.isPending.value ? 'refresh' : 'upload'" :size="18" :class="{ spin: previewMutation.isPending.value }" />
        <span>
          <strong>{{ previewMutation.isPending.value ? `Llegint ${picked?.name}…` : 'Arrossega aquí «Dades del pressupost.xls»' }}</strong>
          <span class="hint">o fes clic per triar-lo. Primer es mostra què canviarà; no s'escriu res fins que confirmis.</span>
        </span>
      </label>

      <p v-if="previewMutation.isError.value" class="notice notice-error">
        <AppIcon name="alert" :size="15" />
        <span>{{ (previewMutation.error.value as Error).message }}</span>
      </p>

      <div v-if="preview" class="preview">
        <div class="preview-head">
          <strong>{{ preview.centre }} · exercici {{ preview.exercici }}</strong>
          <span class="mono subtle">{{ picked?.name }}</span>
        </div>
        <p v-if="preview.nif_matches === false" class="notice notice-warn">
          <AppIcon name="alert" :size="15" />
          <span>
            El NIF de l'Excel ({{ preview.nif }}) no és el CIF del centre configurat a Dades generals. Comprova que és el
            pressupost d'aquesta escola.
          </span>
        </p>
        <ul class="tally">
          <li><strong>{{ preview.created }}</strong> noves</li>
          <li><strong>{{ preview.updated }}</strong> actualitzades</li>
          <li><strong>{{ preview.unchanged }}</strong> iguals</li>
          <li v-if="preview.retired"><strong>{{ preview.retired }}</strong> retirades <span class="subtle">(amb moviments, es conserven)</span></li>
          <li v-if="preview.removed"><strong>{{ preview.removed }}</strong> esborrades</li>
          <li v-if="preview.context_inherited"><strong>{{ preview.context_inherited }}</strong> amb el context de l'any anterior</li>
        </ul>
        <p class="hint">
          {{ preview.despeses }} partides de despesa i {{ preview.ingressos }} d'ingrés · total despeses
          {{ formatEuros(preview.total_despeses, 2) }}.
          <template v-if="preview.replaces"> Substitueix el pressupost {{ preview.exercici }} que ja hi ha.</template>
        </p>
        <div class="preview-actions">
          <button type="button" class="btn btn-ghost btn-sm" :disabled="importMutation.isPending.value" @click="cancel">Cancel·la</button>
          <button
            type="button"
            class="btn btn-primary btn-sm"
            :disabled="importMutation.isPending.value"
            @click="picked && importMutation.mutate(picked)"
          >
            <AppIcon name="check" :size="14" />
            {{ importMutation.isPending.value ? 'Important…' : `Importa ${preview.exercici}` }}
          </button>
        </div>
        <p v-if="importMutation.isError.value" class="notice notice-error">
          <AppIcon name="alert" :size="15" />
          <span>{{ (importMutation.error.value as Error).message }}</span>
        </p>
      </div>

      <p v-if="imported" class="notice notice-success">
        <AppIcon name="check" :size="15" />
        <span>
          Pressupost {{ imported.exercici }} importat: {{ imported.created }} noves, {{ imported.updated }} actualitzades.
          <RouterLink :to="{ name: 'partides' }">Comença a assignar partides</RouterLink>
        </span>
      </p>
    </div>
  </section>

  <section class="card">
    <div class="card-head">
      <div>
        <h2 class="card-title"><AppIcon name="sparkles" :size="14" class="ai-mark" /> Criteris per a Jev</h2>
        <p class="hint">
          Com tria el centre les partides, en general. Jev ho llegeix cada cop que proposa una partida per a un moviment.
        </p>
      </div>
      <span class="badge" :class="budget?.jev ? 'badge-ai' : 'badge-neutral'">
        <span class="badge-dot" />
        Jev {{ budget?.jev ? 'actiu' : 'no configurat' }}
      </span>
    </div>
    <div class="card-body context-general">
      <textarea
        v-model="general"
        class="textarea"
        rows="5"
        maxlength="4000"
        placeholder="Per exemple: Les fotocòpies de Konica van a «Fotocòpies Konika (Secretaria)». Les compres d'Amazon per a informàtica, a «Material i estris informàtics». Si un pagament és de material per al curs que ve (compres de juny i juliol), tria la partida del curs següent."
      />
      <div class="row-actions">
        <span class="subtle">{{ general.length }}/4000</span>
        <button
          type="button"
          class="btn btn-ghost btn-sm"
          :disabled="general === generalSaved"
          @click="general = generalSaved"
        >
          Descarta
        </button>
        <button
          type="button"
          class="btn btn-primary btn-sm"
          :disabled="general === generalSaved || generalMutation.isPending.value"
          @click="generalMutation.mutate()"
        >
          {{ generalMutation.isPending.value ? 'Desant…' : 'Desa els criteris' }}
        </button>
      </div>
    </div>
  </section>

  <section v-if="budget?.exercici" class="card">
    <div class="card-head">
      <div>
        <h2 class="card-title">Context per partida</h2>
        <p class="hint">
          Quan el nom no ho diu tot: per a què serveix, quins proveïdors hi van, què no hi va.
          {{ withContext }} partides en tenen.
        </p>
      </div>
    </div>
    <div class="lines-tools">
      <label class="search">
        <AppIcon name="search" :size="14" />
        <input v-model="query" type="search" placeholder="Cerca per nom, codi o fons…" aria-label="Cerca partides" />
      </label>
      <label class="check"><input v-model="onlyWithContext" type="checkbox" /> Només amb context</label>
      <label class="check"><input v-model="withIncome" type="checkbox" /> Ingressos</label>
    </div>
    <ul class="lines">
      <template v-for="p in rows" :key="p.id">
        <li v-if="p.te_fills" class="line-heading">
          <span class="mono">{{ p.codi }}</span>
          {{ p.nom }}
        </li>
        <li v-else class="line" :class="{ 'is-editing': editing === p.id }">
          <span class="stripe" :style="{ background: fundTone(p.fons).solid }" :title="p.fons_label" />
          <div class="line-body">
            <div class="line-top">
              <span class="line-name">{{ p.nom }}</span>
              <span class="line-meta mono">
                {{ p.codi }}<template v-if="p.codi_finalista"> · {{ p.codi_finalista }}</template>
              </span>
              <span class="line-budget mono">{{ formatEuros(p.import_pressupost) }}</span>
            </div>
            <template v-if="editing === p.id">
              <textarea
                :id="`context-${p.id}`"
                v-model="editText"
                class="textarea"
                rows="2"
                maxlength="4000"
                placeholder="Per exemple: autocars de les sortides d'infantil pagades per les famílies."
                @keydown.meta.enter="saveLine(p)"
                @keydown.ctrl.enter="saveLine(p)"
                @keydown.esc="editing = null"
              />
              <div class="row-actions">
                <button type="button" class="btn btn-ghost btn-sm" @click="editing = null">Cancel·la</button>
                <button type="button" class="btn btn-primary btn-sm" :disabled="lineMutation.isPending.value" @click="saveLine(p)">
                  Desa
                </button>
              </div>
            </template>
            <button v-else-if="p.context" type="button" class="line-context" title="Edita el context" @click="edit(p)">
              {{ p.context }}
            </button>
            <button v-else type="button" class="line-add" @click="edit(p)">
              <AppIcon name="plus" :size="12" /> Afegeix context
            </button>
          </div>
        </li>
      </template>
      <li v-if="!rows.length" class="empty">Cap partida amb aquests filtres.</li>
    </ul>
  </section>
</template>

<style scoped>
.facts {
  display: grid;
  grid-template-columns: repeat(5, minmax(0, auto));
  margin: 0;
  border-bottom: 1px solid var(--line);
}

.fact {
  display: grid;
  gap: 3px;
  min-width: 0;
  padding: 10px 16px;
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
  font-size: var(--text-base);
}

.import {
  display: grid;
  gap: 12px;
  padding: 14px 16px;
}

.where {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
}

.where-label {
  color: var(--ink-400);
  font-size: var(--text-xs);
  font-weight: 600;
  letter-spacing: 0.04em;
  text-transform: uppercase;
}

.crumbs {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 4px;
  margin: 0;
  padding: 0;
  list-style: none;
}

.crumbs li {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 2px 8px;
  border: 1px solid var(--line);
  border-radius: var(--r-sm);
  background: var(--surface-1);
  color: var(--ink-700);
  font-size: var(--text-sm);
  font-weight: 500;
}

.crumbs li:first-child {
  border-color: var(--accent-200);
  background: var(--accent-50);
  color: var(--accent-700);
  font-weight: 600;
}

.crumbs li:last-child {
  border-color: var(--olive-200);
  background: var(--olive-100);
  color: var(--olive-700);
}

.crumbs li + li::before {
  content: '›';
  margin: 0 4px 0 -2px;
  color: var(--ink-400);
}

.drop {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 16px;
  border: 1.5px dashed var(--line-strong);
  border-radius: var(--r-lg);
  background: var(--surface-1);
  color: var(--ink-500);
  cursor: pointer;
}

.drop span {
  display: grid;
  gap: 2px;
}

.drop strong {
  color: var(--ink-700);
  font-size: var(--text-base);
}

.drop.is-over {
  border-color: var(--accent-500);
  background: var(--accent-50);
}

.drop.is-busy {
  cursor: progress;
}

.preview {
  display: grid;
  gap: 8px;
  padding: 12px 14px;
  border: 1px solid var(--accent-200);
  border-radius: var(--r-lg);
  background: var(--accent-50);
}

.preview-head {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 8px;
}

.tally {
  display: flex;
  flex-wrap: wrap;
  gap: 4px 16px;
  margin: 0;
  padding: 0;
  list-style: none;
  font-size: var(--text-base);
}

.preview-actions {
  display: flex;
  justify-content: flex-end;
  gap: 6px;
}

.context-general {
  display: grid;
  gap: 8px;
}

.row-actions {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 6px;
}

.row-actions .subtle {
  margin-right: auto;
  font-size: var(--text-xs);
}

/* ── Lines ────────────────────────────────────────────────────────────── */
.lines-tools {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 12px;
  padding: 10px 16px;
  border-bottom: 1px solid var(--line);
}

.search {
  display: flex;
  flex: 1;
  align-items: center;
  gap: 8px;
  min-width: 220px;
  height: 30px;
  padding: 0 10px;
  border: 1px solid var(--line-strong);
  border-radius: var(--r-md);
  background: var(--surface-0);
  color: var(--ink-400);
}

.search input {
  flex: 1;
  border: 0;
  outline: 0;
  background: none;
  color: var(--ink-900);
  font: inherit;
}

.check {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  color: var(--ink-500);
  font-size: var(--text-sm);
}

.check input {
  accent-color: var(--accent-700);
}

.lines {
  max-height: 560px;
  margin: 0;
  padding: 0;
  overflow-y: auto;
  list-style: none;
}

.line-heading {
  position: sticky;
  top: 0;
  z-index: 1;
  padding: 6px 16px;
  border-bottom: 1px solid var(--line);
  background: var(--surface-1);
  color: var(--ink-700);
  font-size: var(--text-xs);
  font-weight: 600;
  letter-spacing: 0.02em;
  text-transform: uppercase;
}

.line-heading .mono {
  margin-right: 6px;
  color: var(--ink-400);
  text-transform: none;
}

.line {
  display: flex;
  gap: 10px;
  padding: 8px 16px;
  border-bottom: 1px solid var(--line);
}

.line.is-editing {
  background: var(--accent-50);
}

.stripe {
  flex-shrink: 0;
  width: 3px;
  border-radius: 2px;
}

.line-body {
  display: grid;
  flex: 1;
  gap: 4px;
  min-width: 0;
}

.line-top {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto auto;
  align-items: baseline;
  gap: 12px;
}

.line-name {
  font-size: var(--text-base);
}

.line-meta,
.line-budget {
  color: var(--ink-400);
  font-size: var(--text-xs);
}

.line-context {
  padding: 4px 8px;
  border: 0;
  border-left: 2px solid var(--accent-400);
  border-radius: 0 var(--r-sm) var(--r-sm) 0;
  background: var(--surface-1);
  color: var(--ink-700);
  font: inherit;
  font-size: var(--text-sm);
  text-align: left;
  white-space: pre-line;
  cursor: text;
}

.line-add {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  justify-self: start;
  padding: 0;
  border: 0;
  background: none;
  color: var(--ink-400);
  font: inherit;
  font-size: var(--text-xs);
  cursor: pointer;
}

.line-add:hover,
.line-add:focus-visible {
  color: var(--accent-700);
}

.select-sm {
  width: auto;
  height: 30px;
}

@media (max-width: 860px) {
  .facts {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .fact + .fact {
    border-left: 0;
  }

  .line-top {
    grid-template-columns: minmax(0, 1fr);
    gap: 2px;
  }
}
</style>
