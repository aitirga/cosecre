<script setup lang="ts">
/**
 * A list's search box, with the option to ask in plain words.
 *
 * Plain mode filters as you type, like any search. The "IA" switch turns it
 * into a question: Enter sends it, and the answer comes back as the list's own
 * chips and search words — set as a person would set them, so they stay
 * visible, editable and undoable. What the AI understood floats under the box
 * (never pushing the list down), with "Desfés", and — when the question asked
 * for a figure — the figure or a small table and the query behind it.
 *
 * Violet, because it is the AI acting.
 */
import { computed, ref, watch } from 'vue'
import { useMutation } from '@tanstack/vue-query'

import { ApiError } from '../api/client'
import type { AiFilterResult } from '../api/types'
import AnchoredPopover from './AnchoredPopover.vue'
import AppIcon from './AppIcon.vue'

const model = defineModel<string>({ required: true })
const props = withDefaults(
  defineProps<{
    ask: (question: string) => Promise<AiFilterResult>
    placeholder?: string
    label?: string
    aiPlaceholder?: string
    examples?: string[]
    /** Remembers the chosen mode in this browser, per list. */
    storageKey?: string
    defaultAi?: boolean
  }>(),
  {
    placeholder: 'Cerca…',
    label: undefined,
    aiPlaceholder: 'Pregunta-ho amb les teves paraules…',
    examples: () => [],
    storageKey: undefined,
    defaultAi: false,
  },
)
const emit = defineEmits<{ apply: [result: AiFilterResult]; undo: [] }>()

// ── Mode ────────────────────────────────────────────────────────────────────
function storedMode(): boolean {
  if (!props.storageKey) return props.defaultAi
  try {
    const raw = window.localStorage.getItem(`cosecre.aiSearch.${props.storageKey}`)
    return raw === null ? props.defaultAi : raw === 'ai'
  } catch {
    return props.defaultAi
  }
}

const aiMode = ref(storedMode())
watch(aiMode, (on) => {
  if (!props.storageKey) return
  try {
    window.localStorage.setItem(`cosecre.aiSearch.${props.storageKey}`, on ? 'ai' : 'text')
  } catch {
    // Remembered for this visit only.
  }
})

const root = ref<HTMLElement | null>(null)
const input = ref<HTMLInputElement | null>(null)
const focused = ref(false)
const question = ref('')

function toggleMode() {
  aiMode.value = !aiMode.value
  input.value?.focus()
}

// ── Asking ──────────────────────────────────────────────────────────────────
const understood = ref<AiFilterResult | null>(null)
const error = ref('')
const showResult = ref(false)

const askMutation = useMutation({
  mutationFn: (text: string) => props.ask(text),
  onSuccess: (result) => {
    error.value = ''
    understood.value = result
    showResult.value = true
    emit('apply', result)
  },
  onError: (err) => {
    error.value = err instanceof ApiError ? err.message : "No s'ha pogut entendre la pregunta."
    showResult.value = true
  },
})

function submit(text = question.value) {
  const query = text.trim()
  if (query.length < 2 || askMutation.isPending.value) return
  question.value = query
  askMutation.mutate(query)
}

function undo() {
  emit('undo')
  understood.value = null
  showResult.value = false
  question.value = ''
  input.value?.focus()
}

function onEscape() {
  if (aiMode.value && question.value) question.value = ''
  else if (!aiMode.value) model.value = ''
}

const showExamples = computed(
  () => aiMode.value && focused.value && !question.value && !showResult.value && props.examples.length > 0,
)
const popoverOpen = computed(() => (showResult.value && (understood.value || error.value)) || showExamples.value)
const wide = computed(() => Boolean(understood.value?.answer?.rows?.length && (understood.value.answer.columns.length ?? 0) > 1))

// ── The answer to a question for a figure ───────────────────────────────────
/** Euros where the column says so, plain numbers otherwise, text as it is. */
function cell(value: unknown, column: string) {
  if (value == null || value === '') return '—'
  if (typeof value !== 'number') return String(value)
  const money = /€|import|total|gast/i.test(column)
  return value.toLocaleString('ca-ES', {
    minimumFractionDigits: money ? 2 : 0,
    maximumFractionDigits: 2,
    ...(money ? { style: 'currency', currency: 'EUR' } : {}),
  })
}

function usedJev(result: AiFilterResult) {
  return Object.values(result.sources).some((s) => s.source.includes('jev'))
}
</script>

<template>
  <span ref="root" class="ai-search" :class="{ ai: aiMode, busy: askMutation.isPending.value }">
    <AppIcon :name="aiMode ? 'sparkles' : 'search'" :size="14" class="lead" />
    <input
      v-if="aiMode"
      ref="input"
      v-model="question"
      class="input"
      type="search"
      maxlength="500"
      :placeholder="aiPlaceholder"
      :aria-label="`${label ?? placeholder} amb IA`"
      @keydown.enter.prevent="submit()"
      @keydown.esc="onEscape"
      @focus="focused = true"
      @blur="focused = false"
    />
    <input
      v-else
      ref="input"
      v-model="model"
      class="input"
      type="search"
      :placeholder="placeholder"
      :aria-label="label ?? placeholder"
      @keydown.esc="onEscape"
    />
    <span class="trail">
      <button
        v-if="understood && !showResult"
        class="said-pill"
        type="button"
        title="Mostra què ha entès la IA"
        @click="showResult = true"
      >
        <AppIcon name="sparkle" :size="11" />
        Entès
      </button>
      <button
        v-if="!aiMode && model"
        class="clear"
        type="button"
        aria-label="Esborra la cerca"
        @click="model = ''"
      >
        <AppIcon name="close" :size="12" />
      </button>
      <button
        class="mode"
        :class="{ on: aiMode }"
        type="button"
        :aria-pressed="aiMode"
        :title="aiMode ? 'Torna a la cerca de text' : 'Pregunta-ho amb IA'"
        @click="toggleMode"
      >
        <span v-if="askMutation.isPending.value" class="dots" aria-label="Pensant"><i /><i /><i /></span>
        <template v-else>
          <AppIcon name="sparkles" :size="12" />
          IA
        </template>
      </button>
    </span>
  </span>

  <AnchoredPopover
    v-if="popoverOpen"
    :anchor="root"
    :width="wide ? 520 : 380"
    label="Cerca amb IA"
    @close="showResult = false; focused = false"
  >
    <div v-if="showExamples" class="examples" @mousedown.prevent>
      <span class="examples-label">Prova:</span>
      <button v-for="example in examples" :key="example" class="example" type="button" @click="submit(example)">
        {{ example }}
      </button>
    </div>

    <div v-else class="result">
      <p v-if="error" class="said error">
        <AppIcon name="alert" :size="13" />
        <span>{{ error }}</span>
      </p>
      <template v-else-if="understood">
        <div class="said">
          <AppIcon name="sparkle" :size="13" class="said-icon" />
          <span class="said-text">
            <strong>Entès:</strong>
            {{ understood.explanation || 'He posat els filtres.' }}
            <span v-if="understood.models.openai === 'skipped'" class="by" title="Jev l'ha resolt sol, sense consultar el model de llenguatge">· resolt per Jev</span>
            <span v-else-if="usedJev(understood)" class="by" title="Jev ha confirmat els filtres de llista tancada">· confirmat per Jev</span>
          </span>
        </div>

        <section v-if="understood.answer" class="answer">
          <p v-if="understood.answer.error" class="answer-note error">
            <AppIcon name="alert" :size="13" />
            <span>No s'ha pogut calcular: {{ understood.answer.error }}</span>
          </p>
          <p v-else-if="!understood.answer.rows.length" class="answer-note">Cap resultat.</p>
          <div v-else-if="understood.answer.rows.length === 1 && understood.answer.columns.length === 1" class="figure">
            <span class="figure-label">{{ understood.answer.columns[0] }}</span>
            <span class="figure-value">{{ cell(understood.answer.rows[0]?.[0], understood.answer.columns[0] ?? '') }}</span>
          </div>
          <div v-else class="answer-table">
            <table>
              <thead>
                <tr>
                  <th v-for="(column, c) in understood.answer.columns" :key="c" :class="{ num: typeof understood.answer.rows[0]?.[c] === 'number' }">
                    {{ column }}
                  </th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="(row, r) in understood.answer.rows" :key="r">
                  <td v-for="(value, c) in row" :key="c" :class="{ num: typeof value === 'number' }">
                    {{ cell(value, understood.answer.columns[c] ?? '') }}
                  </td>
                </tr>
              </tbody>
            </table>
            <p v-if="understood.answer.truncated" class="answer-note">Només es mostren les 100 primeres files.</p>
          </div>
          <details class="sql">
            <summary>Consulta SQL</summary>
            <pre class="mono">{{ understood.answer.sql }}</pre>
          </details>
        </section>

        <div class="actions">
          <button class="btn btn-ghost btn-sm" type="button" @click="undo">
            <AppIcon name="undo" :size="13" />
            Desfés
          </button>
          <button class="btn btn-ghost btn-sm" type="button" @click="showResult = false">Amaga</button>
        </div>
      </template>
    </div>
  </AnchoredPopover>
</template>

<style scoped>
.ai-search {
  position: relative;
  display: inline-flex;
  align-items: center;
  min-width: 0;
}

.lead {
  position: absolute;
  left: 9px;
  color: var(--ink-400);
  pointer-events: none;
}

.ai .lead {
  color: var(--ai-500);
}

.input {
  width: 100%;
  padding-left: 29px;
  padding-right: 64px;
}

.ai .input {
  border-color: var(--ai-200);
  background: linear-gradient(90deg, var(--ai-50), var(--surface-0) 70%);
}

.ai .input:focus {
  border-color: var(--ai-400);
  box-shadow: 0 0 0 3px var(--ai-100);
}

.busy .input {
  background-size: 200% 100%;
  background-image: linear-gradient(90deg, var(--ai-50), var(--ai-100), var(--ai-50));
  animation: shimmer 1.2s linear infinite;
}

@keyframes shimmer {
  to {
    background-position: -200% 0;
  }
}

/* The browser's own clear control would sit beside ours. */
.input::-webkit-search-cancel-button {
  display: none;
}

.trail {
  position: absolute;
  right: 4px;
  display: inline-flex;
  align-items: center;
  gap: 2px;
}

.clear {
  display: grid;
  place-items: center;
  width: 18px;
  height: 18px;
  padding: 0;
  border: 0;
  border-radius: var(--r-xs);
  background: none;
  color: var(--ink-400);
  cursor: pointer;
}

.clear:hover {
  background: var(--surface-2);
  color: var(--ink-900);
}

.mode {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 3px;
  min-width: 38px;
  height: 22px;
  padding: 0 6px;
  border: 1px solid var(--ai-200);
  border-radius: var(--r-sm);
  background: var(--surface-0);
  font: inherit;
  font-size: 10px;
  font-weight: 700;
  letter-spacing: 0.04em;
  color: var(--ai-700);
  cursor: pointer;
}

.mode:hover {
  background: var(--ai-50);
}

.mode.on {
  border-color: var(--ai-600);
  background: var(--ai-600);
  color: #fff;
}

.said-pill {
  display: inline-flex;
  align-items: center;
  gap: 3px;
  height: 20px;
  padding: 0 6px;
  border: 0;
  border-radius: var(--r-full);
  background: var(--ai-100);
  font: inherit;
  font-size: var(--text-xs);
  color: var(--ai-700);
  cursor: pointer;
}

.dots {
  display: inline-flex;
  gap: 3px;
}

.dots i {
  width: 4px;
  height: 4px;
  border-radius: var(--r-full);
  background: currentColor;
  animation: blink 1s ease-in-out infinite;
}

.dots i:nth-child(2) {
  animation-delay: 0.15s;
}

.dots i:nth-child(3) {
  animation-delay: 0.3s;
}

@keyframes blink {
  50% {
    opacity: 0.25;
  }
}

/* ── The floating panel ──────────────────────────────────────────────── */
.examples {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 6px;
  padding: 8px;
  font-size: var(--text-sm);
}

.examples-label {
  color: var(--ink-400);
}

.example {
  padding: 2px 9px;
  border: 1px solid var(--ai-100);
  border-radius: var(--r-full);
  background: var(--ai-50);
  font: inherit;
  font-size: var(--text-sm);
  color: var(--ai-700);
  cursor: pointer;
}

.example:hover {
  border-color: var(--ai-200);
  background: var(--ai-100);
}

.result {
  display: grid;
  gap: 8px;
  padding: 8px;
  font-size: var(--text-sm);
}

.said {
  display: flex;
  align-items: flex-start;
  gap: 8px;
  margin: 0;
  padding: 6px 8px;
  border-radius: var(--r-md);
  background: var(--ai-50);
  color: var(--ai-800);
  line-height: 1.45;
}

.said.error {
  background: var(--danger-100);
  color: var(--danger-700);
}

.said-icon {
  flex: none;
  margin-top: 2px;
  color: var(--ai-500);
}

.said-text {
  flex: 1;
  min-width: 0;
}

.by {
  color: var(--ai-700);
  opacity: 0.8;
}

.answer {
  display: grid;
  gap: 6px;
}

.figure {
  display: flex;
  align-items: baseline;
  gap: 10px;
  padding: 0 4px;
}

.figure-label {
  color: var(--ink-500);
}

.figure-value {
  font-size: 20px;
  font-weight: 600;
  font-variant-numeric: tabular-nums;
  color: var(--ink-900);
}

.answer-table {
  max-height: 240px;
  overflow: auto;
}

.answer-table table {
  width: 100%;
  border-collapse: collapse;
}

.answer-table th,
.answer-table td {
  padding: 3px 8px;
  border-bottom: 1px solid var(--line);
  text-align: left;
  white-space: nowrap;
}

.answer-table th {
  position: sticky;
  top: 0;
  background: var(--surface-0);
  font-size: var(--text-xs);
  font-weight: 600;
  color: var(--ink-500);
}

.answer-table .num {
  text-align: right;
  font-variant-numeric: tabular-nums;
}

.answer-note {
  display: flex;
  align-items: center;
  gap: 6px;
  margin: 0;
  color: var(--ink-500);
}

.answer-note.error {
  color: var(--danger-700);
}

.sql summary {
  width: max-content;
  font-size: var(--text-xs);
  color: var(--ink-400);
  cursor: pointer;
}

.sql pre {
  margin: 4px 0 0;
  padding: 6px 8px;
  overflow-x: auto;
  border-radius: var(--r-sm);
  background: var(--surface-1);
  font-size: var(--text-xs);
  white-space: pre-wrap;
  color: var(--ink-700);
}

.actions {
  display: flex;
  justify-content: flex-end;
  gap: 4px;
}

@media (prefers-reduced-motion: reduce) {
  .busy .input,
  .dots i {
    animation: none;
  }
}
</style>
