<script setup lang="ts">
/**
 * The printable PDF, exactly as it will be printed — Word files are shown
 * after LibreOffice converts them, so the preview cannot drift from the paper.
 */
import { computed, onBeforeUnmount, ref, shallowRef, watch } from 'vue'

import type { Job } from '../../print/contract'
import { isCancellation, loadPdf, renderPage, type LoadedPdf, type RenderTask } from '../../print/pdf'
import { usePrint } from '../../print/usePrint'
import AppIcon from '../AppIcon.vue'

const props = defineProps<{ job: Job | undefined }>()

const ZOOM_STEPS = [0.5, 0.75, 1, 1.25, 1.5, 2]

const print = usePrint()
const loaded = shallowRef<LoadedPdf | null>(null)
const page = ref(1)
const zoom = ref(1)
const error = ref<string | null>(null)
const loading = ref(false)

const canvas = ref<HTMLCanvasElement | null>(null)
const stage = ref<HTMLDivElement | null>(null)

// Guards against an out-of-order load resolving after a newer one.
let loadToken = 0
// The render currently painting the canvas, so a new draw can cancel it.
let renderTask: RenderTask | null = null
let pending: Promise<void> = Promise.resolve()

const pageCount = computed(() => loaded.value?.doc.numPages ?? 0)
const converting = computed(() => props.job?.extension === '.docx' && !props.job.printablePath)

function release() {
  const previous = loaded.value
  loaded.value = null
  if (previous) void previous.destroy()
}

// Keyed on a string, not a tuple: every queue update hands over a fresh job
// object, and a getter returning a new array would reload — and destroy — the
// document on each one, mid-render.
watch(
  () => (props.job?.printablePath ? props.job.id : ''),
  async (jobId) => {
    const token = ++loadToken
    release()
    error.value = null
    if (!jobId) return

    loading.value = true
    try {
      const next = await loadPdf(await print.readPrintable(jobId))
      if (token !== loadToken) {
        void next.destroy()
        return
      }
      loaded.value = next
      page.value = 1
      void print.reportPageCount(jobId, next.doc.numPages)
    } catch (cause) {
      if (token === loadToken) error.value = cause instanceof Error ? cause.message : String(cause)
    } finally {
      if (token === loadToken) loading.value = false
    }
  },
  { immediate: true },
)

async function draw() {
  const doc = loaded.value?.doc
  if (!doc || !canvas.value || !stage.value) return

  // Stop any render still in flight, and wait for it to settle — resizes and
  // page changes arrive in bursts, and overlapping renders half-paint a page.
  renderTask?.cancel()
  await pending.catch(() => undefined)

  const width = Math.max(180, (stage.value.clientWidth - 48) * zoom.value)
  const run = renderPage(doc, page.value, canvas.value, width, (task) => (renderTask = task))
  pending = run
  try {
    await run
    error.value = null
  } catch (cause) {
    if (!isCancellation(cause)) error.value = cause instanceof Error ? cause.message : String(cause)
  } finally {
    if (pending === run) renderTask = null
  }
}

watch([loaded, page, zoom, canvas], () => void draw(), { flush: 'post' })

// Re-render on resize so the page keeps filling the pane.
const observer = new ResizeObserver(() => void draw())
watch(stage, (element, previous) => {
  if (previous) observer.unobserve(previous)
  if (element) observer.observe(element)
})

onBeforeUnmount(() => {
  observer.disconnect()
  loadToken++
  release()
})

function zoomIn() {
  zoom.value = ZOOM_STEPS.find((step) => step > zoom.value) ?? zoom.value
}

function zoomOut() {
  zoom.value = [...ZOOM_STEPS].reverse().find((step) => step < zoom.value) ?? zoom.value
}
</script>

<template>
  <div v-if="!job" class="empty fill">
    <AppIcon name="printer" :size="30" />
    <strong>Cap document seleccionat</strong>
    <span>Tria'n un de la cua per veure'l tal com s'imprimirà.</span>
  </div>

  <div v-else-if="converting" class="empty fill">
    <template v-if="job.status === 'failed'">
      <AppIcon name="alert" :size="28" />
      <strong>No s'ha pogut convertir</strong>
      <span>{{ job.error }}</span>
    </template>
    <template v-else>
      <AppIcon name="refresh" :size="24" class="spin" />
      <strong>Convertint a PDF…</strong>
      <span>Els Word es converteixen amb LibreOffice perquè la vista prèvia sigui el que s'imprimeix.</span>
    </template>
  </div>

  <div v-else class="preview">
    <div class="bar">
      <div class="title">
        <strong class="truncate">{{ job.fileName }}</strong>
        <span class="muted">
          {{ loaded ? `${pageCount} ${pageCount === 1 ? 'pàgina' : 'pàgines'}` : 'Carregant…' }}
        </span>
      </div>
      <div class="controls">
        <button class="btn btn-ghost btn-icon btn-sm" type="button" title="Pàgina anterior" :disabled="!loaded || page <= 1" @click="page--">
          <AppIcon name="chevronLeft" />
        </button>
        <span class="readout">{{ loaded ? `${page} / ${pageCount}` : '—' }}</span>
        <button class="btn btn-ghost btn-icon btn-sm" type="button" title="Pàgina següent" :disabled="!loaded || page >= pageCount" @click="page++">
          <AppIcon name="chevron" />
        </button>
        <span class="divider" />
        <button class="btn btn-ghost btn-icon btn-sm" type="button" title="Redueix" :disabled="zoom <= ZOOM_STEPS[0]!" @click="zoomOut">
          <AppIcon name="minus" />
        </button>
        <span class="readout">{{ Math.round(zoom * 100) }}%</span>
        <button class="btn btn-ghost btn-icon btn-sm" type="button" title="Amplia" :disabled="zoom >= ZOOM_STEPS[ZOOM_STEPS.length - 1]!" @click="zoomIn">
          <AppIcon name="plus" />
        </button>
      </div>
    </div>

    <div ref="stage" class="stage">
      <div v-if="error" class="empty">
        <AppIcon name="alert" :size="28" />
        <strong>No es pot mostrar aquest document</strong>
        <span>{{ error }}</span>
      </div>
      <AppIcon v-else-if="loading && !loaded" name="refresh" :size="22" class="spin loader" />
      <canvas v-show="!error && loaded" ref="canvas" class="page" />
    </div>
  </div>
</template>

<style scoped>
.fill {
  height: 100%;
  align-content: center;
}

.fill strong,
.stage .empty strong {
  color: var(--ink-700);
  font-weight: 600;
}

.fill span {
  max-width: 340px;
}

.preview {
  display: flex;
  flex-direction: column;
  height: 100%;
  min-height: 0;
}

.bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 8px 12px;
  border-bottom: 1px solid var(--line);
  background: var(--surface-0);
}

.title {
  display: grid;
  min-width: 0;
  font-size: var(--text-base);
}

.title .muted {
  font-size: var(--text-xs);
}

.controls {
  display: flex;
  align-items: center;
  gap: 2px;
  flex-shrink: 0;
}

.readout {
  min-width: 48px;
  text-align: center;
  font-size: var(--text-sm);
  font-variant-numeric: tabular-nums;
  color: var(--ink-500);
}

.divider {
  width: 1px;
  height: 18px;
  margin: 0 6px;
  background: var(--line);
}

.stage {
  flex: 1;
  min-height: 0;
  overflow: auto;
  display: flex;
  justify-content: center;
  align-items: flex-start;
  padding: 24px;
  background: var(--surface-3);
}

.loader {
  margin-top: 64px;
  color: var(--ink-400);
}

.page {
  flex-shrink: 0;
  border-radius: var(--r-xs);
  background: #fff;
  box-shadow:
    0 0 0 1px var(--line-strong),
    var(--shadow-lg);
}
</style>
