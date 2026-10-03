<script setup lang="ts">
import { computed } from 'vue'

import type { HistoryAction } from '../api/types'
import { useHistory } from '../composables/useHistory'
import AppIcon from './AppIcon.vue'

/**
 * Everything that has changed, by anyone, newest first. Any line can be undone
 * (or redone) on its own; the hub refuses when something changed it since.
 */
const { historyQuery, undo, redo, busy } = useHistory()
const actions = computed(() => historyQuery.data.value?.actions ?? [])

const STATE_LABEL: Record<HistoryAction['state'], string> = {
  done: '',
  undone: 'Desfet',
  dropped: 'Desfet',
}

function when(iso: string) {
  return new Date(iso).toLocaleString('ca-ES', { dateStyle: 'short', timeStyle: 'short' })
}

function who(action: HistoryAction) {
  if (action.kind === 'auto') return 'Cosecre'
  return action.mine ? 'Tu' : action.user_name ?? '—'
}
</script>

<template>
  <section class="card">
    <div class="card-head">
      <div>
        <h2 class="card-title">Historial</h2>
        <p class="hint">
          Tot el que ha canviat, de més nou a més antic. Qualsevol canvi es pot desfer i tornar a fer; si després algú ha
          tocat el mateix, no es desfà i t’ho diu. <span class="mono">⌘Z</span> / <span class="mono">⇧⌘Z</span> desfan i
          refan els teus.
        </p>
      </div>
    </div>
    <div class="card-body">
      <p v-if="historyQuery.isLoading.value" class="muted">Carregant…</p>
      <p v-else-if="!actions.length" class="muted">Encara no hi ha cap canvi registrat.</p>
      <div v-else class="table-scroll">
        <table class="table">
          <thead>
            <tr>
              <th>Quan</th>
              <th>Qui</th>
              <th>Què</th>
              <th />
            </tr>
          </thead>
          <tbody>
            <tr v-for="action in actions" :key="action.id" :class="{ off: action.state !== 'done' }">
              <td class="mono muted nowrap">{{ when(action.created_at) }}</td>
              <td class="nowrap">{{ who(action) }}</td>
              <td>
                <strong>{{ action.label }}</strong>
                <span v-if="action.detail" class="muted"> · {{ action.detail }}</span>
                <span v-if="STATE_LABEL[action.state]" class="tag">{{ STATE_LABEL[action.state] }}</span>
              </td>
              <td class="actions">
                <button
                  v-if="action.state === 'done'"
                  class="btn btn-ghost btn-sm"
                  type="button"
                  :disabled="busy"
                  @click="undo(action.id)"
                >
                  <AppIcon name="undo" :size="13" /> Desfés
                </button>
                <button v-else class="btn btn-ghost btn-sm" type="button" :disabled="busy" @click="redo(action.id)">
                  <AppIcon name="redo" :size="13" /> Refés
                </button>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>
  </section>
</template>

<style scoped>
.nowrap {
  white-space: nowrap;
}

.actions {
  text-align: right;
  white-space: nowrap;
}

tr.off strong {
  text-decoration: line-through;
  color: var(--ink-500);
}

.tag {
  margin-left: 6px;
  padding: 0 5px;
  border: 1px solid var(--line);
  border-radius: var(--r-sm);
  font-size: var(--text-xs);
  color: var(--ink-500);
}
</style>
