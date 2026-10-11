<script setup lang="ts">
import { computed } from 'vue'

import type { AssistantBlock, AssistantMessage, AssistantProposal } from '../../api/types'
import AppIcon from '../AppIcon.vue'
import AssistantChart from './AssistantChart.vue'
import AssistantProposalCard from './AssistantProposalCard.vue'
import AssistantTable from './AssistantTable.vue'
import { renderMarkdown } from './markdown'

type Step = Extract<AssistantBlock, { type: 'step' }>

const props = defineProps<{
  message: AssistantMessage
  /** Set while the answer is still arriving: what it is doing now. */
  working?: string
}>()
const emit = defineEmits<{ proposal: [proposal: AssistantProposal] }>()

/** Runs of steps fold into one line, so the answer reads first. */
type Piece = { kind: 'steps'; steps: Step[] } | { kind: 'block'; block: AssistantBlock }

const pieces = computed<Piece[]>(() => {
  const out: Piece[] = []
  for (const block of props.message.blocks) {
    if (block.type === 'step') {
      const last = out[out.length - 1]
      if (last?.kind === 'steps') last.steps.push(block)
      else out.push({ kind: 'steps', steps: [block] })
    } else if (block.type !== 'text' || block.text.trim()) {
      out.push({ kind: 'block', block })
    }
  }
  return out
})

const TOOL_LABEL: Record<string, string> = {
  run_sql: 'Consulta',
  call_api: 'Lectura',
  list_api: 'Catàleg de l’API',
  propose_changes: 'Proposta',
  show_table: 'Taula',
  show_chart: 'Gràfic',
  show_metrics: 'Xifres',
}

function stepsSummary(steps: Step[]) {
  const queries = steps.filter((s) => s.tool === 'run_sql').length
  const reads = steps.filter((s) => s.tool === 'call_api' || s.tool === 'list_api').length
  const failed = steps.filter((s) => !s.ok).length
  const parts = []
  if (queries) parts.push(`${queries} ${queries === 1 ? 'consulta' : 'consultes'}`)
  if (reads) parts.push(`${reads} ${reads === 1 ? 'lectura' : 'lectures'} del hub`)
  if (!parts.length) parts.push(`${steps.length} ${steps.length === 1 ? 'pas' : 'passos'}`)
  return `${parts.join(' · ')}${failed ? ` · ${failed} amb error` : ''}`
}
</script>

<template>
  <article v-if="message.role === 'user'" class="msg user">
    <p class="bubble">{{ message.content }}</p>
  </article>

  <article v-else class="msg assistant">
    <div class="avatar" aria-hidden="true"><AppIcon name="sparkle" :size="14" /></div>
    <div class="body">
      <template v-for="(piece, index) in pieces" :key="index">
        <details v-if="piece.kind === 'steps'" class="steps">
          <summary>
            <AppIcon name="database" :size="12" />
            {{ stepsSummary(piece.steps) }}
          </summary>
          <ol>
            <li v-for="(step, s) in piece.steps" :key="s" :class="{ failed: !step.ok }">
              <div class="step-head">
                <span class="step-tool">{{ TOOL_LABEL[step.tool] ?? step.tool }}</span>
                <span v-if="step.purpose" class="step-purpose">{{ step.purpose }}</span>
                <span v-else-if="step.path" class="step-purpose mono">{{ step.path }}</span>
                <span v-else-if="step.search" class="step-purpose">«{{ step.search }}»</span>
                <span class="step-detail">{{ step.detail }}</span>
              </div>
              <pre v-if="step.sql" class="sql">{{ step.sql }}</pre>
            </li>
          </ol>
        </details>

        <div
          v-else-if="piece.block.type === 'text'"
          class="prose"
          v-html="renderMarkdown(piece.block.text)"
        />
        <AssistantTable v-else-if="piece.block.type === 'table'" :table="piece.block" />
        <AssistantChart v-else-if="piece.block.type === 'chart'" :chart="piece.block" />
        <section v-else-if="piece.block.type === 'metrics'" class="metrics">
          <p v-if="piece.block.title" class="metrics-title">{{ piece.block.title }}</p>
          <div class="tiles">
            <div v-for="(item, i) in piece.block.items" :key="i" class="tile">
              <span class="tile-label">{{ item.label }}</span>
              <span class="tile-value">{{ item.value }}</span>
              <span v-if="item.hint" class="tile-hint">{{ item.hint }}</span>
            </div>
          </div>
        </section>
        <template v-else-if="piece.block.type === 'proposal'">
          <AssistantProposalCard
            v-if="piece.block.proposal"
            :proposal="piece.block.proposal"
            @updated="emit('proposal', $event)"
          />
        </template>
      </template>

      <p v-if="working" class="working">
        <span class="dots" aria-hidden="true"><i /><i /><i /></span>
        {{ working }}
      </p>
      <p v-if="message.status === 'error' && message.detail" class="failure">
        <AppIcon name="alert" :size="13" />
        {{ message.detail }}
      </p>
    </div>
  </article>
</template>

<style scoped>
.msg {
  display: flex;
  gap: 10px;
}

.user {
  justify-content: flex-end;
}

.bubble {
  max-width: min(640px, 85%);
  padding: 8px 12px;
  border-radius: var(--r-lg);
  background: var(--accent-50);
  border: 1px solid var(--accent-100);
  font-size: var(--text-md);
  white-space: pre-wrap;
  overflow-wrap: anywhere;
}

.avatar {
  display: grid;
  flex: none;
  place-items: center;
  width: 26px;
  height: 26px;
  border-radius: var(--r-md);
  background: var(--ai-100);
  color: var(--ai-600);
}

.body {
  display: grid;
  flex: 1;
  gap: 10px;
  min-width: 0;
  padding-top: 2px;
}

/* ── Text ─────────────────────────────────────────────────────────────── */

.prose {
  font-size: var(--text-md);
  line-height: 1.6;
  color: var(--ink-900);
  overflow-wrap: anywhere;
}

.prose :deep(p + p),
.prose :deep(p + ul),
.prose :deep(p + ol),
.prose :deep(ul + p),
.prose :deep(ol + p),
.prose :deep(.md-table + p),
.prose :deep(p + .md-table) {
  margin-top: 8px;
}

.prose :deep(h3),
.prose :deep(h4),
.prose :deep(h5) {
  margin: 12px 0 4px;
  font-size: var(--text-md);
}

.prose :deep(ul),
.prose :deep(ol) {
  margin: 4px 0;
  padding-left: 20px;
}

.prose :deep(li + li) {
  margin-top: 2px;
}

.prose :deep(code) {
  padding: 1px 4px;
  border-radius: var(--r-xs);
  background: var(--surface-2);
  font-family: var(--font-mono);
  font-size: 0.86em;
}

.prose :deep(pre) {
  margin: 6px 0;
  padding: 8px 10px;
  border-radius: var(--r-md);
  background: var(--surface-2);
  overflow-x: auto;
}

.prose :deep(pre code) {
  padding: 0;
  background: none;
}

.prose :deep(blockquote) {
  margin: 6px 0;
  padding-left: 10px;
  border-left: 2px solid var(--line-strong);
  color: var(--ink-500);
}

.prose :deep(a) {
  color: var(--accent-700);
  text-decoration: underline;
}

.prose :deep(.md-table) {
  overflow-x: auto;
}

.prose :deep(table) {
  border-collapse: collapse;
  font-size: var(--text-base);
}

.prose :deep(th),
.prose :deep(td) {
  padding: 4px 10px 4px 0;
  border-bottom: 1px solid var(--line);
  text-align: left;
}

.prose :deep(th) {
  font-weight: 600;
  color: var(--ink-700);
}

/* ── Steps ────────────────────────────────────────────────────────────── */

.steps {
  font-size: var(--text-sm);
  color: var(--ink-400);
}

.steps summary {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  cursor: pointer;
  list-style: none;
  user-select: none;
}

.steps summary::-webkit-details-marker {
  display: none;
}

.steps summary:hover {
  color: var(--ink-700);
}

.steps ol {
  display: grid;
  gap: 6px;
  margin: 6px 0 0;
  padding: 0 0 0 10px;
  border-left: 1px solid var(--line);
  list-style: none;
}

.step-head {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  align-items: baseline;
}

.step-tool {
  font-weight: 600;
  color: var(--ink-500);
}

.failed .step-tool,
.failed .step-detail {
  color: var(--danger-700);
}

.step-purpose {
  color: var(--ink-500);
}

.mono {
  font-family: var(--font-mono);
}

.step-detail {
  color: var(--ink-400);
}

.sql {
  margin: 4px 0 0;
  padding: 6px 8px;
  border-radius: var(--r-sm);
  background: var(--surface-2);
  font-family: var(--font-mono);
  font-size: var(--text-xs);
  color: var(--ink-700);
  white-space: pre-wrap;
  overflow-wrap: anywhere;
}

/* ── Figures ──────────────────────────────────────────────────────────── */

.metrics-title {
  margin-bottom: 6px;
  font-size: var(--text-base);
  font-weight: 600;
}

.tiles {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(150px, 1fr));
  gap: 8px;
}

.tile {
  display: grid;
  gap: 2px;
  padding: 10px 12px;
  border: 1px solid var(--line);
  border-radius: var(--r-lg);
  background: var(--surface-0);
}

.tile-label {
  font-size: var(--text-sm);
  color: var(--ink-500);
}

.tile-value {
  font-size: var(--text-xl);
  font-weight: 600;
  color: var(--ink-900);
  font-variant-numeric: tabular-nums;
}

.tile-hint {
  font-size: var(--text-xs);
  color: var(--ink-400);
}

/* ── State ────────────────────────────────────────────────────────────── */

.working {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  font-size: var(--text-sm);
  color: var(--ai-700);
}

.dots {
  display: inline-flex;
  gap: 3px;
}

.dots i {
  width: 5px;
  height: 5px;
  border-radius: 50%;
  background: var(--ai-500);
  animation: pulse 1s ease-in-out infinite;
}

.dots i:nth-child(2) {
  animation-delay: 0.15s;
}

.dots i:nth-child(3) {
  animation-delay: 0.3s;
}

@keyframes pulse {
  0%,
  100% {
    opacity: 0.25;
  }
  50% {
    opacity: 1;
  }
}

.failure {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 7px 10px;
  border: 1px solid var(--danger-200);
  border-radius: var(--r-md);
  background: var(--danger-100);
  font-size: var(--text-sm);
  color: var(--danger-700);
}
</style>
