<script setup lang="ts">
/**
 * "Ask the register": a question in plain words, turned into the register's
 * own filters. The AI never filters on its own terms — it sets the same chips
 * a person would, so what it understood is visible, editable, and undoable.
 *
 * Violet, because it is the AI acting.
 */
import { ref } from 'vue'
import { useMutation } from '@tanstack/vue-query'

import { api, ApiError } from '../api/client'
import type { AiFilterResult } from '../api/types'
import AppIcon from './AppIcon.vue'

const emit = defineEmits<{ apply: [result: AiFilterResult]; undo: [] }>()
const props = defineProps<{ examples: string[] }>()

const question = ref('')
const focused = ref(false)
const error = ref('')
/** The last reading, shown until the next question or until dismissed. */
const understood = ref<AiFilterResult | null>(null)
const input = ref<HTMLInputElement | null>(null)

const ask = useMutation({
  mutationFn: (query: string) => api.aiFilter(query),
  onSuccess: (result) => {
    error.value = ''
    understood.value = result
    emit('apply', result)
  },
  onError: (err) => {
    error.value = err instanceof ApiError ? err.message : "No s'ha pogut entendre la pregunta."
  },
})

function submit(text = question.value) {
  const query = text.trim()
  if (query.length < 2 || ask.isPending.value) return
  question.value = query
  ask.mutate(query)
}

function undo() {
  emit('undo')
  understood.value = null
  question.value = ''
  input.value?.focus()
}

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

function isNumber(value: unknown) {
  return typeof value === 'number'
}

function usedJev(result: AiFilterResult) {
  return Object.values(result.sources).some((s) => s.source.includes('jev'))
}
</script>

<template>
  <div class="ai" :class="{ busy: ask.isPending.value, focused }">
    <form class="ask" @submit.prevent="submit()">
      <AppIcon name="sparkles" :size="15" class="spark" />
      <input
        ref="input"
        v-model="question"
        type="text"
        maxlength="500"
        placeholder="Pregunta-ho: «factures pendents de la papereria d'aquest curs»"
        aria-label="Filtra el registre amb una pregunta"
        @focus="focused = true"
        @blur="focused = false"
        @keydown.esc="question = ''"
      />
      <button class="btn btn-ai btn-sm go" type="submit" :disabled="question.trim().length < 2 || ask.isPending.value">
        <span v-if="ask.isPending.value" class="dots" aria-label="Pensant"><i /><i /><i /></span>
        <template v-else>Filtra</template>
      </button>
    </form>

    <!-- Shown while the box has focus, so they are there when wanted and quiet otherwise. -->
    <div v-if="focused && !understood && !error && !question" class="examples">
      <span class="examples-label">Prova:</span>
      <button
        v-for="example in props.examples"
        :key="example"
        class="example"
        type="button"
        @mousedown.prevent
        @click="submit(example)"
      >
        {{ example }}
      </button>
    </div>

    <p v-if="error" class="said error">
      <AppIcon name="alert" :size="13" />
      <span>{{ error }}</span>
    </p>
    <div v-else-if="understood" class="said">
      <AppIcon name="sparkle" :size="13" class="said-icon" />
      <span class="said-text">
        <strong>Entès:</strong>
        {{ understood.explanation || 'He posat els filtres de sota.' }}
        <span v-if="understood.models.openai === 'skipped'" class="by" title="Jev l'ha resolt sol, sense consultar el model de llenguatge">· resolt per Jev</span>
        <span v-else-if="usedJev(understood)" class="by" title="Jev ha confirmat els filtres de llista tancada">· confirmat per Jev</span>
      </span>
      <button class="btn btn-ghost btn-sm" type="button" @click="undo">
        <AppIcon name="undo" :size="13" />
        Desfés
      </button>
      <button class="dismiss" type="button" aria-label="Amaga" title="Amaga" @click="understood = null">
        <AppIcon name="close" :size="12" />
      </button>
    </div>

    <!-- A question for a figure: the answer above, the documents behind it in the list below. -->
    <section v-if="understood?.answer" class="answer">
      <p v-if="understood.answer.error" class="answer-error">
        <AppIcon name="alert" :size="13" />
        <span>No s'ha pogut calcular: {{ understood.answer.error }}</span>
      </p>
      <p v-else-if="!understood.answer.rows.length" class="answer-empty">Cap resultat.</p>
      <div
        v-else-if="understood.answer.rows.length === 1 && understood.answer.columns.length === 1"
        class="figure"
      >
        <span class="figure-label">{{ understood.answer.columns[0] }}</span>
        <span class="figure-value">{{ cell(understood.answer.rows[0]?.[0], understood.answer.columns[0] ?? '') }}</span>
      </div>
      <div v-else class="answer-table">
        <table>
          <thead>
            <tr>
              <th v-for="(column, c) in understood.answer.columns" :key="c" :class="{ num: isNumber(understood.answer.rows[0]?.[c]) }">
                {{ column }}
              </th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="(row, r) in understood.answer.rows" :key="r">
              <td v-for="(value, c) in row" :key="c" :class="{ num: isNumber(value) }">
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
  </div>
</template>

<style scoped>
.ai {
  display: grid;
  gap: 8px;
}

.ask {
  display: flex;
  align-items: center;
  gap: 8px;
  height: 38px;
  padding: 0 4px 0 12px;
  border: 1px solid var(--ai-200);
  border-radius: var(--r-lg);
  background: linear-gradient(90deg, var(--ai-50), var(--surface-0) 70%);
  transition:
    border-color 0.12s ease,
    box-shadow 0.12s ease;
}

.focused .ask {
  border-color: var(--ai-400);
  box-shadow: 0 0 0 3px var(--ai-100);
}

.busy .ask {
  background-size: 200% 100%;
  background-image: linear-gradient(90deg, var(--ai-50), var(--ai-100), var(--ai-50));
  animation: shimmer 1.2s linear infinite;
}

@keyframes shimmer {
  to {
    background-position: -200% 0;
  }
}

.spark {
  flex: none;
  color: var(--ai-500);
}

.ask input {
  flex: 1;
  min-width: 0;
  height: 100%;
  border: 0;
  outline: none;
  background: none;
  font: inherit;
  font-size: var(--text-base);
  color: var(--ink-900);
}

.ask input::placeholder {
  color: var(--ink-400);
}

.go {
  flex: none;
  min-width: 64px;
  justify-content: center;
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

.examples {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 6px;
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

.answer {
  display: grid;
  gap: 6px;
  padding: 8px 10px;
  border: 1px solid var(--ai-100);
  border-radius: var(--r-md);
  background: var(--surface-0);
  font-size: var(--text-sm);
}

.figure {
  display: flex;
  align-items: baseline;
  gap: 10px;
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
  max-height: 260px;
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

.answer-error,
.answer-empty,
.answer-note {
  display: flex;
  align-items: center;
  gap: 6px;
  margin: 0;
  color: var(--ink-500);
}

.answer-error {
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

.said {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 6px 6px 6px 10px;
  border-radius: var(--r-md);
  background: var(--ai-50);
  font-size: var(--text-sm);
  color: var(--ai-800);
}

.said.error {
  background: var(--danger-100);
  color: var(--danger-700);
}

.said-icon {
  flex: none;
  color: var(--ai-500);
}

.said-text {
  flex: 1;
  min-width: 0;
}

.by {
  color: var(--ai-700);
  opacity: 0.75;
}

.dismiss {
  display: grid;
  place-items: center;
  width: 22px;
  height: 22px;
  padding: 0;
  border: 0;
  border-radius: var(--r-sm);
  background: none;
  color: var(--ai-700);
  cursor: pointer;
}

.dismiss:hover {
  background: var(--ai-100);
}
</style>
