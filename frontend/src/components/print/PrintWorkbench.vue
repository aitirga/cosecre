<script setup lang="ts">
/**
 * The print tool, as the desktop shell runs it.
 *
 * Three panes side by side — the queue, the page as it will print, and that
 * document's options — so a batch can be checked and sent without opening
 * anything. Loaded on demand: it pulls in pdf.js, which a browser never needs.
 */
import { onMounted, ref } from 'vue'

import { usePrint } from '../../print/usePrint'
import AppIcon from '../AppIcon.vue'
import PrintHistory from './PrintHistory.vue'
import PrintJobList from './PrintJobList.vue'
import PrintOptionsPanel from './PrintOptionsPanel.vue'
import PrintPreview from './PrintPreview.vue'
import PrintSettingsDialog from './PrintSettingsDialog.vue'

const print = usePrint()
const tab = ref<'queue' | 'history'>('queue')
const settingsOpen = ref(false)
const loadError = ref<string | null>(null)

onMounted(() => {
  print.init().catch((error: unknown) => {
    loadError.value = error instanceof Error ? error.message : String(error)
  })
})

// ── Drop target ────────────────────────────────────────────────────────────
// Drag events fire for every child element, so a naive enter/leave pair
// flickers; counting them is what keeps the overlay steady.
const dragging = ref(false)
let depth = 0

function onDragEnter(event: DragEvent) {
  depth += 1
  if (event.dataTransfer?.types.includes('Files')) dragging.value = true
}

function onDragLeave() {
  depth = Math.max(0, depth - 1)
  if (depth === 0) dragging.value = false
}

function onDrop(event: DragEvent) {
  depth = 0
  dragging.value = false
  if (event.dataTransfer?.files.length) {
    tab.value = 'queue'
    void print.addDropped(event.dataTransfer.files)
  }
}

function printAll() {
  void print.printJobs(print.pending.value.map((job) => job.id))
}
</script>

<template>
  <div
    class="print"
    @dragenter.prevent="onDragEnter"
    @dragover.prevent
    @dragleave.prevent="onDragLeave"
    @drop.prevent="onDrop"
  >
    <header class="page-head">
      <div>
        <h1 class="page-title">Impressió</h1>
        <p class="page-lead">
          PDF i Word en lot: cada document a la seva impressora, i totes treballant alhora.
        </p>
      </div>
      <div class="head-actions">
        <span v-if="print.sendingCount.value" class="sending">
          <span class="badge-dot badge-dot-pulse" />
          {{ print.sendingCount.value }} imprimint
        </span>
        <button class="btn btn-outline" type="button" @click="print.pickFiles()">
          <AppIcon name="plus" />
          Afegeix fitxers
        </button>
        <button class="btn btn-primary" type="button" :disabled="!print.pending.value.length" @click="printAll">
          <AppIcon name="printer" />
          Imprimeix-ho tot{{ print.pending.value.length ? ` (${print.pending.value.length})` : '' }}
        </button>
        <button class="btn btn-ghost btn-icon" type="button" title="Ajustos d'impressió" @click="settingsOpen = true">
          <AppIcon name="sliders" />
        </button>
      </div>
    </header>

    <p v-if="loadError" class="notice notice-error">
      <AppIcon name="alert" :size="15" />
      <span>No s'ha pogut iniciar la impressió: {{ loadError }}</span>
    </p>

    <p v-if="print.needsConverter.value" class="notice notice-warn">
      <AppIcon name="alert" :size="15" />
      <span>{{ print.state.converter?.reason }}</span>
      <button class="link" type="button" @click="settingsOpen = true">Obre els ajustos</button>
    </p>

    <section class="card bench">
      <nav class="tabs" aria-label="Impressió">
        <button class="tab" :class="{ active: tab === 'queue' }" type="button" @click="tab = 'queue'">
          <AppIcon name="file" :size="14" />
          Cua
          <span v-if="print.state.jobs.length" class="count">{{ print.state.jobs.length }}</span>
        </button>
        <button class="tab" :class="{ active: tab === 'history' }" type="button" @click="tab = 'history'">
          <AppIcon name="history" :size="14" />
          Historial
        </button>
        <button
          v-if="tab === 'queue' && print.finishedCount.value"
          class="btn btn-ghost btn-sm tabs-end"
          type="button"
          @click="print.clearFinished()"
        >
          Treu els acabats
        </button>
      </nav>

      <PrintHistory v-if="tab === 'history'" class="pane-fill" />
      <div v-else class="panes">
        <div class="pane list">
          <PrintJobList />
        </div>
        <div class="pane preview">
          <PrintPreview :job="print.selectedJob.value" />
        </div>
        <div class="pane options">
          <PrintOptionsPanel :job="print.selectedJob.value" />
        </div>
      </div>
    </section>

    <div v-if="dragging" class="drop" aria-hidden="true">
      <div class="drop-box">
        <AppIcon name="printer" :size="32" />
        <strong>Deixa'ls anar per afegir-los a la cua</strong>
        <span>PDF i Word (.docx)</span>
      </div>
    </div>

    <div class="toasts" role="status">
      <p v-for="notice in print.state.notices" :key="notice.id" class="toast" :class="notice.tone">
        <AppIcon :name="notice.tone === 'error' ? 'alert' : 'check'" :size="14" />
        <span>{{ notice.text }}</span>
        <button class="btn btn-ghost btn-icon btn-sm" type="button" title="Tanca" @click="print.dismiss(notice.id)">
          <AppIcon name="close" />
        </button>
      </p>
    </div>

    <PrintSettingsDialog v-if="settingsOpen" @close="settingsOpen = false" />
  </div>
</template>

<style scoped>
.print {
  display: flex;
  flex-direction: column;
  gap: 14px;
  /* The bench fills the window: content padding and the desktop footer
     account for the 100px. */
  height: calc(100vh - 100px);
  min-height: 520px;
}

.head-actions {
  display: flex;
  align-items: center;
  gap: 8px;
}

.sending {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  margin-right: 4px;
  font-size: var(--text-sm);
  font-weight: 500;
  color: var(--accent-700);
}

.notice .link {
  margin-left: auto;
  padding: 0;
  border: 0;
  background: none;
  font-size: var(--text-sm);
  text-decoration: underline;
  text-underline-offset: 2px;
  white-space: nowrap;
}

.bench {
  flex: 1;
  min-height: 0;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.tabs {
  display: flex;
  align-items: center;
  gap: 2px;
  padding: 0 8px;
  border-bottom: 1px solid var(--line);
}

.tab {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 9px 10px 8px;
  border: 0;
  border-bottom: 2px solid transparent;
  margin-bottom: -1px;
  background: none;
  font-size: var(--text-base);
  font-weight: 500;
  color: var(--ink-500);
}

.tab:hover {
  color: var(--ink-900);
}

.tab.active {
  color: var(--accent-700);
  border-bottom-color: var(--accent-600);
}

.count {
  padding: 0 6px;
  border-radius: var(--r-full);
  background: var(--surface-2);
  font-size: var(--text-xs);
  font-variant-numeric: tabular-nums;
  color: var(--ink-500);
}

.tab.active .count {
  background: var(--accent-100);
  color: var(--accent-700);
}

.tabs-end {
  margin-left: auto;
}

.pane-fill {
  flex: 1;
  min-height: 0;
}

.panes {
  flex: 1;
  min-height: 0;
  display: grid;
  grid-template-columns: minmax(220px, 280px) minmax(0, 1fr) minmax(220px, 264px);
}

.pane {
  min-width: 0;
  min-height: 0;
}

.pane.list {
  overflow-y: auto;
  border-right: 1px solid var(--line);
}

.pane.options {
  border-left: 1px solid var(--line);
}

/* ── Drop overlay ───────────────────────────────────────────────────────── */
.drop {
  position: fixed;
  inset: 0;
  z-index: 90;
  display: grid;
  place-items: center;
  background: color-mix(in srgb, var(--surface-1) 82%, transparent);
  backdrop-filter: blur(2px);
  pointer-events: none;
}

.drop-box {
  display: grid;
  justify-items: center;
  gap: 6px;
  padding: 40px 64px;
  border: 2px dashed var(--accent-400);
  border-radius: var(--r-xl);
  background: var(--surface-0);
  color: var(--accent-600);
  box-shadow: var(--shadow-lg);
}

.drop-box strong {
  color: var(--ink-900);
  font-size: var(--text-md);
}

.drop-box span {
  color: var(--ink-400);
  font-size: var(--text-sm);
}

/* ── Toasts ─────────────────────────────────────────────────────────────── */
.toasts {
  position: fixed;
  right: 18px;
  bottom: 18px;
  z-index: 80;
  display: grid;
  gap: 6px;
  width: min(360px, calc(100vw - 36px));
  pointer-events: none;
}

.toast {
  display: flex;
  align-items: flex-start;
  gap: 8px;
  padding: 8px 6px 8px 10px;
  border: 1px solid var(--line);
  border-radius: var(--r-md);
  background: var(--surface-0);
  box-shadow: var(--shadow-md);
  font-size: var(--text-sm);
  pointer-events: auto;
}

.toast > svg {
  margin-top: 2px;
  flex-shrink: 0;
  color: var(--olive-700);
}

.toast span {
  flex: 1;
}

.toast.error {
  border-color: var(--danger-200);
  background: var(--danger-100);
  color: var(--danger-700);
}

.toast.error > svg {
  color: inherit;
}

@media (max-width: 1100px) {
  .panes {
    grid-template-columns: minmax(200px, 240px) minmax(0, 1fr) minmax(200px, 230px);
  }
}
</style>
