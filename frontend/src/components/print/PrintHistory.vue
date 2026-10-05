<script setup lang="ts">
import { computed, ref } from 'vue'

import type { HistoryEntry } from '../../print/contract'
import { formatBytes, formatDuration, formatTime, STATUS_BADGE, STATUS_LABEL } from '../../print/format'
import { usePrint } from '../../print/usePrint'
import AppIcon from '../AppIcon.vue'

type StatusFilter = 'all' | HistoryEntry['status']

const print = usePrint()
const query = ref('')
const status = ref<StatusFilter>('all')

const filtered = computed(() => {
  const needle = query.value.trim().toLowerCase()
  return print.state.history.filter((entry) => {
    if (status.value !== 'all' && entry.status !== status.value) return false
    if (!needle) return true
    return entry.fileName.toLowerCase().includes(needle) || entry.printer.toLowerCase().includes(needle)
  })
})

function settings(entry: HistoryEntry) {
  return [
    entry.copies > 1 ? `×${entry.copies}` : '',
    entry.pages ? `p. ${entry.pages}` : 'totes',
    entry.duplex !== 'simplex' ? 'doble cara' : '',
    entry.color === 'monochrome' ? 'B/N' : '',
    entry.paperSize,
  ]
    .filter(Boolean)
    .join(' · ')
}

function clear() {
  if (window.confirm('Vols esborrar tot l’historial d’impressió?')) void print.clearHistory()
}
</script>

<template>
  <div class="history">
    <div class="toolbar">
      <input v-model="query" class="input search" placeholder="Cerca per fitxer o impressora…" />
      <select v-model="status" class="select status">
        <option value="all">Tots els estats</option>
        <option value="completed">Impresos</option>
        <option value="failed">Amb error</option>
        <option value="canceled">Cancel·lats</option>
      </select>
      <span class="count muted">{{ filtered.length }} de {{ print.state.history.length }}</span>
      <button class="btn btn-ghost btn-sm" type="button" :disabled="!print.state.history.length" @click="clear">
        <AppIcon name="trash" />
        Esborra
      </button>
    </div>

    <div v-if="!filtered.length" class="empty">
      <AppIcon name="history" :size="28" />
      <strong>{{ print.state.history.length ? 'Res no coincideix amb el filtre' : 'Encara no s’ha imprès res' }}</strong>
      <span v-if="!print.state.history.length">Cada document que acaba queda apuntat aquí.</span>
    </div>

    <div v-else class="table-scroll scroller">
      <table class="table">
        <thead>
          <tr>
            <th>Document</th>
            <th>Impressora</th>
            <th>Opcions</th>
            <th>Acabat</th>
            <th class="num">Durada</th>
            <th>Estat</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="entry in filtered" :key="`${entry.id}-${entry.finishedAt}`">
            <td class="doc">
              <span class="truncate name" :title="entry.sourcePath">{{ entry.fileName }}</span>
              <span class="muted small">
                {{ formatBytes(entry.sizeBytes) }}{{ entry.pageCount ? ` · ${entry.pageCount} p.` : '' }}
              </span>
              <span v-if="entry.error" class="error small">{{ entry.error }}</span>
            </td>
            <td class="truncate printer">{{ entry.printer }}</td>
            <td class="subtle small">{{ settings(entry) }}</td>
            <td class="nowrap subtle">{{ formatTime(entry.finishedAt) }}</td>
            <td class="num subtle">{{ formatDuration(entry.durationMs) }}</td>
            <td>
              <span class="badge" :class="STATUS_BADGE[entry.status]">{{ STATUS_LABEL[entry.status] }}</span>
            </td>
          </tr>
        </tbody>
      </table>
    </div>
  </div>
</template>

<style scoped>
.history {
  display: flex;
  flex-direction: column;
  height: 100%;
  min-height: 0;
}

.toolbar {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 10px 12px;
  border-bottom: 1px solid var(--line);
}

.search {
  max-width: 280px;
}

.status {
  width: auto;
}

.count {
  margin-left: auto;
  font-size: var(--text-sm);
}

.empty strong {
  color: var(--ink-700);
  font-weight: 600;
}

.scroller {
  flex: 1;
  min-height: 0;
  overflow: auto;
}

.doc {
  display: grid;
  max-width: 320px;
}

.name {
  color: var(--ink-900);
}

.printer {
  max-width: 200px;
}

.small {
  font-size: var(--text-xs);
}

.nowrap {
  white-space: nowrap;
}

.error {
  color: var(--danger-700);
}
</style>
