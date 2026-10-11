<script setup lang="ts">
/**
 * A PDF original drawn in place, page under page, so it can be read against
 * the fields beside it — while the AI is still reading it, too. pdf.js comes
 * in with this component only, so a register that never shows a PDF never
 * downloads it.
 */
import { computed, onBeforeUnmount, ref, shallowRef, watch } from 'vue'

import { isCancellation, loadPdf, renderPage, type LoadedPdf, type RenderTask } from '../print/pdf'
import AppIcon from './AppIcon.vue'

const props = defineProps<{ src: string }>()
const emit = defineEmits<{ open: [] }>()

/** An invoice is a page or three; past this, the full viewer is the better tool. */
const MAX_PAGES = 20
const ZOOM_STEPS = [1, 1.5, 2, 3]

const loaded = shallowRef<LoadedPdf | null>(null)
const error = ref('')
const loading = ref(true)
const zoom = ref(1)
const current = ref(1)

const stage = ref<HTMLElement | null>(null)
const canvases = ref<HTMLCanvasElement[]>([])

const pageCount = computed(() => loaded.value?.doc.numPages ?? 0)
const shown = computed(() => Math.min(pageCount.value, MAX_PAGES))

let loadToken = 0
function release() {
  const previous = loaded.value
  loaded.value = null
  if (previous) void previous.destroy()
}

watch(
  () => props.src,
  async (src) => {
    const token = ++loadToken
    release()
    error.value = ''
    loading.value = true
    try {
      const data = new Uint8Array(await (await fetch(src)).arrayBuffer())
      const next = await loadPdf(data)
      if (token !== loadToken) return void next.destroy()
      loaded.value = next
      current.value = 1
    } catch (cause) {
      if (token === loadToken) error.value = cause instanceof Error ? cause.message : String(cause)
    } finally {
      if (token === loadToken) loading.value = false
    }
  },
  { immediate: true },
)

// ── Drawing ──────────────────────────────────────────────────────────────────
// Every draw cancels the one before and waits for it: resizes come in bursts,
// and pdf.js will not paint one canvas twice at once.
const tasks = new Set<RenderTask>()
let pending: Promise<unknown> = Promise.resolve()
let drawToken = 0

async function draw() {
  const doc = loaded.value?.doc
  if (!doc || !stage.value) return
  const token = ++drawToken
  for (const task of tasks) task.cancel()
  await pending.catch(() => undefined)
  if (token !== drawToken) return

  const width = Math.max(160, (stage.value.clientWidth - 14) * zoom.value)
  const run = (async () => {
    for (let index = 0; index < shown.value; index++) {
      const canvas = canvases.value[index]
      if (!canvas || token !== drawToken) return
      await renderPage(doc, index + 1, canvas, width, (task) => tasks.add(task))
    }
  })()
  pending = run
  try {
    await run
  } catch (cause) {
    if (!isCancellation(cause)) error.value = cause instanceof Error ? cause.message : String(cause)
  } finally {
    if (token === drawToken) tasks.clear()
  }
}

watch([loaded, zoom], () => void draw(), { flush: 'post' })

let resizeTimer: number | undefined
let lastWidth = 0
const observer = new ResizeObserver(([entry]) => {
  const width = Math.round(entry?.contentRect.width ?? 0)
  if (width === lastWidth) return
  lastWidth = width
  window.clearTimeout(resizeTimer)
  resizeTimer = window.setTimeout(() => void draw(), 120)
})
watch(stage, (element, previous) => {
  if (previous) observer.unobserve(previous)
  if (element) observer.observe(element)
})

onBeforeUnmount(() => {
  observer.disconnect()
  window.clearTimeout(resizeTimer)
  for (const task of tasks) task.cancel()
  loadToken++
  drawToken++
  release()
})

// ── Reading along ────────────────────────────────────────────────────────────
function onScroll() {
  const element = stage.value
  if (!element) return
  const line = element.scrollTop + element.clientHeight / 3
  let page = 1
  canvases.value.forEach((canvas, index) => {
    if (canvas.offsetTop <= line) page = index + 1
  })
  current.value = page
}

function zoomIn() {
  zoom.value = ZOOM_STEPS.find((step) => step > zoom.value) ?? zoom.value
}

function zoomOut() {
  zoom.value = [...ZOOM_STEPS].reverse().find((step) => step < zoom.value) ?? zoom.value
}
</script>

<template>
  <div class="pdf">
    <div class="bar">
      <span class="mono pages">
        <template v-if="pageCount">{{ current }} / {{ pageCount }}</template>
        <template v-else>PDF</template>
      </span>
      <span class="spacer" />
      <button class="tool" type="button" title="Redueix" :disabled="zoom <= ZOOM_STEPS[0]!" @click="zoomOut">
        <AppIcon name="minus" :size="13" />
        <span class="sr-only">Redueix</span>
      </button>
      <span class="mono zoom">{{ Math.round(zoom * 100) }}%</span>
      <button
        class="tool"
        type="button"
        title="Amplia"
        :disabled="zoom >= ZOOM_STEPS[ZOOM_STEPS.length - 1]!"
        @click="zoomIn"
      >
        <AppIcon name="plus" :size="13" />
        <span class="sr-only">Amplia</span>
      </button>
      <button class="tool" type="button" title="Obre en una pestanya nova" @click="emit('open')">
        <AppIcon name="external" :size="13" />
        <span class="sr-only">Obre en una pestanya nova</span>
      </button>
    </div>

    <div ref="stage" class="stage" @scroll.passive="onScroll">
      <p v-if="loading" class="hint state">Carregant el PDF…</p>
      <p v-else-if="error" class="notice notice-error state">
        <AppIcon name="alert" :size="15" />
        <span>No s'ha pogut mostrar el PDF. {{ error }}</span>
      </p>
      <template v-else>
        <canvas v-for="index in shown" :key="index" ref="canvases" class="page" />
        <p v-if="pageCount > shown" class="hint state">
          Es mostren les primeres {{ shown }} pàgines de {{ pageCount }}.
        </p>
      </template>
    </div>
  </div>
</template>

<style scoped>
.pdf {
  display: grid;
  grid-template-rows: auto minmax(0, 1fr);
  width: 100%;
  border: 1px solid var(--line);
  border-radius: var(--r-sm);
  background: var(--surface-2);
  overflow: hidden;
}

.bar {
  display: flex;
  align-items: center;
  gap: 2px;
  padding: 3px 4px 3px 8px;
  border-bottom: 1px solid var(--line);
  background: var(--surface-0);
}

.spacer {
  flex: 1;
}

.pages,
.zoom {
  font-size: var(--text-xs);
  color: var(--ink-500);
  font-variant-numeric: tabular-nums;
}

.zoom {
  min-width: 36px;
  text-align: center;
}

.tool {
  display: inline-grid;
  place-items: center;
  width: 24px;
  height: 24px;
  border: 0;
  border-radius: var(--r-xs);
  background: transparent;
  color: var(--ink-500);
  cursor: pointer;
}

.tool:hover:not(:disabled) {
  background: var(--surface-2);
  color: var(--ink-700);
}

.tool:disabled {
  opacity: 0.35;
  cursor: default;
}

.stage {
  display: grid;
  justify-items: start;
  align-content: start;
  gap: 6px;
  height: min(62vh, 560px);
  padding: 6px;
  overflow: auto;
  overscroll-behavior: contain;
}

.page {
  display: block;
  background: #fff;
  box-shadow: 0 0 0 1px var(--line);
}

.state {
  justify-self: stretch;
  margin: 8px 4px;
}
</style>
