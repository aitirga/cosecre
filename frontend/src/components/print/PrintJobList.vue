<script setup lang="ts">
import { isTerminal, type Job } from '../../print/contract'
import { formatBytes, isMoving, STATUS_BADGE, STATUS_LABEL } from '../../print/format'
import { usePrint } from '../../print/usePrint'
import AppIcon from '../AppIcon.vue'

const print = usePrint()

function meta(job: Job) {
  return [
    job.options.printer || 'Sense impressora',
    formatBytes(job.sizeBytes),
    job.pageCount ? `${job.pageCount} p.` : '',
    job.options.copies > 1 ? `×${job.options.copies}` : '',
  ]
    .filter(Boolean)
    .join(' · ')
}
</script>

<template>
  <div v-if="!print.state.jobs.length" class="empty list-empty">
    <AppIcon name="file" :size="28" />
    <strong>No hi ha res a la cua</strong>
    <span>Arrossega PDF o Word a la finestra, o afegeix-los amb el botó.</span>
  </div>

  <ul v-else class="jobs">
    <li v-for="job in print.state.jobs" :key="job.id">
      <div
        class="job"
        :class="{ selected: job.id === print.state.selectedJobId }"
        role="button"
        tabindex="0"
        @click="print.select(job.id)"
        @keydown.enter.space.prevent="print.select(job.id)"
      >
        <div class="row">
          <span class="name truncate" :title="job.sourcePath">{{ job.fileName }}</span>
          <span class="badge" :class="STATUS_BADGE[job.status]">
            <span class="badge-dot" :class="{ 'badge-dot-pulse': isMoving(job.status) }" />
            {{ STATUS_LABEL[job.status] }}
          </span>
        </div>
        <div class="row">
          <span class="meta truncate">{{ meta(job) }}</span>
          <span class="actions">
            <button
              v-if="job.status === 'failed'"
              class="btn btn-ghost btn-icon btn-sm"
              type="button"
              title="Torna-ho a provar"
              @click.stop="print.retryJob(job.id)"
            >
              <AppIcon name="refresh" />
            </button>
            <button
              class="btn btn-ghost btn-icon btn-sm danger"
              type="button"
              :title="isTerminal(job.status) ? 'Treu de la llista' : 'Cancel·la'"
              @click.stop="isTerminal(job.status) ? print.removeJob(job.id) : print.cancelJob(job.id)"
            >
              <AppIcon name="close" />
            </button>
          </span>
        </div>
        <p v-if="job.error" class="error">{{ job.error }}</p>
        <p v-else-if="job.tracking === 'submitted-only' && job.status === 'completed'" class="hint">
          Enviat a la cua del sistema; Windows no informa de cada pàgina.
        </p>
      </div>
    </li>
  </ul>
</template>

<style scoped>
.list-empty {
  height: 100%;
  align-content: center;
}

.list-empty strong {
  color: var(--ink-700);
  font-weight: 600;
}

.jobs {
  display: grid;
  gap: 4px;
  margin: 0;
  padding: 6px;
  list-style: none;
}

.job {
  display: grid;
  gap: 3px;
  padding: 8px 10px;
  border: 1px solid transparent;
  border-radius: var(--r-md);
  cursor: pointer;
}

.job:hover {
  background: var(--surface-2);
}

.job.selected {
  background: var(--accent-50);
  border-color: var(--accent-200);
}

.row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  min-width: 0;
}

.name {
  font-size: var(--text-base);
  font-weight: 500;
  color: var(--ink-900);
}

.meta {
  font-size: var(--text-xs);
  color: var(--ink-400);
}

.actions {
  display: flex;
  gap: 2px;
  opacity: 0;
  transition: opacity 0.12s ease;
}

.job:hover .actions,
.job:focus-within .actions,
.job.selected .actions {
  opacity: 1;
}

.btn.danger:hover:not(:disabled) {
  background: var(--danger-100);
  color: var(--danger-700);
}

.error {
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
  padding: 3px 6px;
  border-radius: var(--r-sm);
  background: var(--danger-100);
  color: var(--danger-700);
  font-size: var(--text-xs);
}
</style>
