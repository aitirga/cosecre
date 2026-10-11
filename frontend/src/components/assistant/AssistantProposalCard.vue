<script setup lang="ts">
import { useQueryClient } from '@tanstack/vue-query'
import { computed, ref } from 'vue'

import { api, ApiError } from '../../api/client'
import type { AssistantAction, AssistantProposal } from '../../api/types'
import AppIcon from '../AppIcon.vue'
import { formatCell } from './format'

/**
 * Changes the Assistent wants to make. Nothing happens until *Aplica*; then
 * they go through as you, as one action the history can undo.
 */
const props = defineProps<{ proposal: AssistantProposal }>()
const emit = defineEmits<{ updated: [proposal: AssistantProposal] }>()

const queryClient = useQueryClient()
const busy = ref<'apply' | 'discard' | 'undo' | null>(null)
const error = ref('')
const undone = ref(false)
const expanded = ref(false)

const VISIBLE = 6
const actions = computed(() => (expanded.value ? props.proposal.actions : props.proposal.actions.slice(0, VISIBLE)))

const STATUS: Record<AssistantProposal['status'], { label: string; badge: string }> = {
  pending: { label: 'Pendent de confirmar', badge: 'badge-ai' },
  applied: { label: 'Aplicada', badge: 'badge-olive' },
  partial: { label: 'Aplicada en part', badge: 'badge-gold' },
  failed: { label: 'Ha fallat', badge: 'badge-danger' },
  stale: { label: 'No aplicada', badge: 'badge-gold' },
  discarded: { label: 'Descartada', badge: 'badge-neutral' },
}

const VERB: Record<AssistantAction['method'], string> = {
  PATCH: 'Edita',
  PUT: 'Substitueix',
  POST: 'Executa',
  DELETE: 'Esborra',
}

const deletes = computed(() => props.proposal.actions.filter((a) => a.method === 'DELETE').length)

function show(value: unknown, field: string) {
  if (value === null || value === undefined || value === '') return '—'
  return formatCell(value, field)
}

function subject(action: AssistantAction) {
  const before = action.before ?? {}
  const parts = [before.num_doc_intern ?? before.codi, before.num_factura, before.proveidor ?? before.concepte]
    .filter((part) => part !== undefined && part !== null && part !== '')
    .map(String)
  return action.label || parts.join(' · ') || action.path
}

function bodyFields(action: AssistantAction) {
  if (action.changes.length || !action.body || typeof action.body !== 'object') return []
  return Object.entries(action.body as Record<string, unknown>)
}

async function run(kind: 'apply' | 'discard') {
  busy.value = kind
  error.value = ''
  try {
    const updated =
      kind === 'apply'
        ? await api.applyAssistantProposal(props.proposal.id)
        : await api.discardAssistantProposal(props.proposal.id)
    emit('updated', updated)
    if (kind === 'apply') void queryClient.invalidateQueries()
  } catch (caught) {
    error.value = caught instanceof ApiError ? caught.message : "No s'ha pogut fer."
  } finally {
    busy.value = null
  }
}

async function undo() {
  if (props.proposal.history_action_id == null) return
  busy.value = 'undo'
  error.value = ''
  try {
    await api.undoAction(props.proposal.history_action_id)
    undone.value = true
    void queryClient.invalidateQueries()
  } catch (caught) {
    error.value = caught instanceof ApiError ? caught.message : "No s'ha pogut desfer."
  } finally {
    busy.value = null
  }
}
</script>

<template>
  <section class="proposal" :class="proposal.status">
    <header class="head">
      <AppIcon name="sparkle" :size="14" class="mark" />
      <span class="summary">{{ proposal.summary }}</span>
      <span class="badge" :class="STATUS[proposal.status].badge">{{ STATUS[proposal.status].label }}</span>
    </header>

    <p class="lead">
      {{ proposal.actions.length }} {{ proposal.actions.length === 1 ? 'canvi' : 'canvis' }}
      <template v-if="deletes"> · <strong class="danger">{{ deletes }} {{ deletes === 1 ? 'esborrat' : 'esborrats' }}</strong></template>
      <template v-if="proposal.status === 'pending'"> · no es farà res fins que l'apliquis.</template>
    </p>

    <ol class="actions">
      <li v-for="(action, index) in actions" :key="index" class="action">
        <div class="action-head">
          <span class="verb" :class="{ danger: action.method === 'DELETE' }">{{ VERB[action.method] }}</span>
          <span class="subject">{{ subject(action) }}</span>
          <span
            v-if="proposal.results[index]"
            class="result"
            :class="proposal.results[index]?.ok ? 'ok' : 'bad'"
            :title="proposal.results[index]?.detail"
          >
            <AppIcon :name="proposal.results[index]?.ok ? 'check' : 'alert'" :size="12" />
          </span>
          <code class="path" :title="`${action.method} ${action.path}`">{{ action.path }}</code>
        </div>
        <table v-if="action.changes.length" class="diff">
          <tbody>
            <tr v-for="change in action.changes" :key="change.field">
              <th>{{ change.field }}</th>
              <td class="before">{{ show(change.before, change.field) }}</td>
              <td class="arrow">→</td>
              <td class="after">{{ show(change.after, change.field) }}</td>
            </tr>
          </tbody>
        </table>
        <table v-else-if="bodyFields(action).length" class="diff">
          <tbody>
            <tr v-for="[field, value] in bodyFields(action)" :key="field">
              <th>{{ field }}</th>
              <td class="after" colspan="3">{{ show(value, field) }}</td>
            </tr>
          </tbody>
        </table>
      </li>
    </ol>
    <button
      v-if="proposal.actions.length > VISIBLE"
      class="btn btn-ghost btn-sm more"
      type="button"
      @click="expanded = !expanded"
    >
      {{ expanded ? 'Mostra menys' : `Mostra els ${proposal.actions.length - VISIBLE} restants` }}
    </button>

    <p v-if="proposal.detail" class="detail">{{ proposal.detail }}</p>
    <p v-if="error" class="detail error">{{ error }}</p>

    <footer v-if="proposal.status === 'pending'" class="foot">
      <button class="btn btn-ai btn-sm" type="button" :disabled="busy !== null" @click="run('apply')">
        <AppIcon name="check" :size="13" />
        {{ busy === 'apply' ? 'Aplicant…' : `Aplica ${proposal.actions.length === 1 ? 'el canvi' : `els ${proposal.actions.length} canvis`}` }}
      </button>
      <button class="btn btn-ghost btn-sm" type="button" :disabled="busy !== null" @click="run('discard')">
        Descarta
      </button>
      <span class="hint-line">Es podrà desfer des de l'historial.</span>
    </footer>
    <footer
      v-else-if="['applied', 'partial'].includes(proposal.status) && proposal.history_action_id != null"
      class="foot"
    >
      <button v-if="!undone" class="btn btn-outline btn-sm" type="button" :disabled="busy !== null" @click="undo">
        <AppIcon name="undo" :size="13" />
        {{ busy === 'undo' ? 'Desfent…' : 'Desfés aquests canvis' }}
      </button>
      <span v-else class="hint-line">Desfet.</span>
    </footer>
  </section>
</template>

<style scoped>
.proposal {
  border: 1px solid var(--ai-200);
  border-radius: var(--r-lg);
  background: var(--surface-0);
  overflow: hidden;
}

.proposal:not(.pending) {
  border-color: var(--line);
}

.head {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 9px 12px;
  background: var(--ai-50);
  border-bottom: 1px solid var(--ai-100);
}

.proposal:not(.pending) .head {
  background: var(--surface-1);
  border-bottom-color: var(--line);
}

.mark {
  color: var(--ai-500);
  flex: none;
}

.summary {
  flex: 1;
  min-width: 0;
  font-size: var(--text-base);
  font-weight: 600;
}

.lead {
  padding: 8px 12px 0;
  font-size: var(--text-sm);
  color: var(--ink-500);
}

.danger {
  color: var(--danger-700);
}

.actions {
  display: grid;
  gap: 6px;
  margin: 0;
  padding: 8px 12px;
  list-style: none;
}

.action {
  padding: 7px 9px;
  border: 1px solid var(--line);
  border-radius: var(--r-md);
  background: var(--surface-1);
}

.action-head {
  display: flex;
  align-items: center;
  gap: 8px;
  min-width: 0;
  font-size: var(--text-sm);
}

.verb {
  flex: none;
  font-weight: 600;
  color: var(--ink-700);
}

.subject {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: var(--ink-900);
}

.path {
  margin-left: auto;
  max-width: 40%;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-family: var(--font-mono);
  font-size: var(--text-xs);
  color: var(--ink-400);
}

.result {
  display: inline-flex;
  flex: none;
}

.result.ok {
  color: var(--olive-700);
}

.result.bad {
  color: var(--danger-700);
}

.diff {
  width: 100%;
  margin-top: 5px;
  border-collapse: collapse;
  font-size: var(--text-sm);
}

.diff th {
  width: 1%;
  padding: 2px 10px 2px 0;
  font-family: var(--font-mono);
  font-size: var(--text-xs);
  font-weight: 500;
  color: var(--ink-400);
  text-align: left;
  white-space: nowrap;
}

.diff td {
  padding: 2px 0;
  vertical-align: top;
}

.before {
  color: var(--ink-400);
  text-decoration: line-through;
  text-decoration-color: var(--line-strong);
}

.arrow {
  width: 1%;
  padding: 2px 8px !important;
  color: var(--ink-400);
}

.after {
  color: var(--ink-900);
  font-weight: 500;
}

.more {
  margin: -2px 0 6px 12px;
}

.detail {
  padding: 0 12px 8px;
  font-size: var(--text-sm);
  color: var(--gold-800);
}

.detail.error {
  color: var(--danger-700);
}

.foot {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 9px 12px;
  border-top: 1px solid var(--line);
}

.hint-line {
  font-size: var(--text-sm);
  color: var(--ink-400);
}
</style>
