<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'

import AppIcon from './AppIcon.vue'

/**
 * The original in a floating window over the page. It is not modal and moves
 * nothing: the list and the proposal stay where they are and stay usable. It
 * opens where the page suggests (`home`), can be dragged by its head and
 * resized from its corner, and remembers both for the next time.
 *
 * Wheel zooms towards the pointer, drag pans, double-click toggles. PDFs get
 * the browser's own viewer.
 */
type Box = { x: number; y: number; w: number; h: number }

const props = defineProps<{
  src: string | null
  type: string
  title: string
  subtitle?: string
  loading?: boolean
  home: () => Box
}>()
const emit = defineEmits<{ close: [] }>()

// ── The window ───────────────────────────────────────────────────────────────

const STORE = 'cosecre.reconcile.peek'
const MIN_W = 300
const MIN_H = 260
const box = ref<Box>({ x: 0, y: 0, w: 440, h: 560 })

function fit(b: Box): Box {
  const w = Math.min(Math.max(b.w, MIN_W), window.innerWidth - 16)
  const h = Math.min(Math.max(b.h, MIN_H), window.innerHeight - 16)
  return {
    w,
    h,
    x: Math.min(Math.max(8, b.x), window.innerWidth - w - 8),
    y: Math.min(Math.max(8, b.y), window.innerHeight - h - 8),
  }
}

function remember() {
  try {
    localStorage.setItem(STORE, JSON.stringify(box.value))
  } catch {
    /* a convenience, not a requirement */
  }
}

function recall(): Box | null {
  try {
    const saved = JSON.parse(localStorage.getItem(STORE) ?? 'null')
    return saved && typeof saved.x === 'number' ? saved : null
  } catch {
    return null
  }
}

let drag: { px: number; py: number; from: Box; mode: 'move' | 'size' } | null = null

function startDrag(event: PointerEvent, mode: 'move' | 'size') {
  if (event.button !== 0 || (mode === 'move' && (event.target as HTMLElement).closest('button, a'))) return
  ;(event.currentTarget as HTMLElement).setPointerCapture(event.pointerId)
  drag = { px: event.clientX, py: event.clientY, from: { ...box.value }, mode }
  event.preventDefault()
}

function moveDrag(event: PointerEvent) {
  if (!drag) return
  const dx = event.clientX - drag.px
  const dy = event.clientY - drag.py
  box.value =
    drag.mode === 'move'
      ? fit({ ...drag.from, x: drag.from.x + dx, y: drag.from.y + dy })
      : fit({ ...drag.from, w: drag.from.w + dx, h: drag.from.h + dy })
}

function endDrag() {
  if (drag) remember()
  drag = null
}

function goHome() {
  box.value = fit(props.home())
  remember()
}

const onResize = () => (box.value = fit(box.value))
onMounted(() => {
  box.value = fit(recall() ?? props.home())
  window.addEventListener('resize', onResize)
})
onBeforeUnmount(() => window.removeEventListener('resize', onResize))

// ── The image ────────────────────────────────────────────────────────────────

const MIN = 1
const MAX = 10
const scale = ref(1)
const rotation = ref(0)
const tx = ref(0)
const ty = ref(0)
const stage = ref<HTMLElement | null>(null)
const panning = ref(false)

const isPdf = computed(() => props.type === 'application/pdf')
const clamp = (value: number, low: number, high: number) => Math.min(high, Math.max(low, value))
const percent = computed(() => `${Math.round(scale.value * 100)}%`)
const transform = computed(
  () => `translate(${tx.value}px, ${ty.value}px) scale(${scale.value}) rotate(${rotation.value}deg)`,
)

function reset() {
  scale.value = 1
  tx.value = 0
  ty.value = 0
}

// A new document starts fitted and upright.
watch(
  () => props.src,
  () => {
    reset()
    rotation.value = 0
  },
)

/** Zoom to `next`, keeping the point (x, y) — in client pixels — still. */
function zoomAt(next: number, x?: number, y?: number) {
  const target = clamp(next, MIN, MAX)
  const rect = stage.value?.getBoundingClientRect()
  if (!rect) return
  const cx = (x ?? rect.left + rect.width / 2) - (rect.left + rect.width / 2)
  const cy = (y ?? rect.top + rect.height / 2) - (rect.top + rect.height / 2)
  const ratio = target / scale.value
  tx.value = cx - (cx - tx.value) * ratio
  ty.value = cy - (cy - ty.value) * ratio
  scale.value = target
  if (target === MIN) reset()
}

function onWheel(event: WheelEvent) {
  event.preventDefault()
  // A trackpad's sideways swipe pans; everything else zooms.
  if (scale.value > 1 && Math.abs(event.deltaX) > Math.abs(event.deltaY)) {
    tx.value -= event.deltaX
    return
  }
  const speed = event.ctrlKey ? 0.01 : 0.0018
  zoomAt(scale.value * Math.exp(-event.deltaY * speed), event.clientX, event.clientY)
}

function onDoubleClick(event: MouseEvent) {
  if (scale.value > 1.05) reset()
  else zoomAt(2.5, event.clientX, event.clientY)
}

function rotate() {
  rotation.value = (rotation.value + 90) % 360
  reset()
}

let last: { x: number; y: number } | null = null

function onPanStart(event: PointerEvent) {
  if (event.button !== 0 && event.button !== 1) return
  ;(event.currentTarget as HTMLElement).setPointerCapture(event.pointerId)
  last = { x: event.clientX, y: event.clientY }
  panning.value = true
}

function onPanMove(event: PointerEvent) {
  if (!last) return
  if (scale.value > 1) {
    tx.value += event.clientX - last.x
    ty.value += event.clientY - last.y
  }
  last = { x: event.clientX, y: event.clientY }
}

function onPanEnd() {
  last = null
  panning.value = false
}
</script>

<template>
  <Teleport to="body">
    <aside
      class="peek"
      role="dialog"
      aria-label="Original de la factura"
      :style="{ left: `${box.x}px`, top: `${box.y}px`, width: `${box.w}px`, height: `${box.h}px` }"
    >
      <header
        class="peek-head"
        title="Arrossega per moure"
        @pointerdown="startDrag($event, 'move')"
        @pointermove="moveDrag"
        @pointerup="endDrag"
        @pointercancel="endDrag"
        @dblclick="goHome"
      >
        <span class="grip" aria-hidden="true" />
        <div class="peek-title">
          <strong class="truncate">{{ props.title }}</strong>
          <span v-if="props.subtitle" class="truncate">{{ props.subtitle }}</span>
        </div>
        <a v-if="props.src" class="icon-btn" :href="props.src" target="_blank" rel="noopener" title="Obre en una pestanya nova">
          <AppIcon name="external" :size="14" />
        </a>
        <button class="icon-btn" type="button" title="Tanca (Esc)" @click="emit('close')">
          <AppIcon name="close" :size="14" />
        </button>
      </header>

      <div v-if="props.loading" class="peek-empty"><span class="shimmer" />Carregant l'original…</div>
      <div v-else-if="!props.src" class="peek-empty">Aquesta factura no té original.</div>
      <iframe v-else-if="isPdf" class="pdf" :src="props.src" :title="props.title" />
      <div
        v-else
        ref="stage"
        class="stage"
        :class="{ panning, zoomed: scale > 1 }"
        @wheel="onWheel"
        @dblclick="onDoubleClick"
        @pointerdown="onPanStart"
        @pointermove="onPanMove"
        @pointerup="onPanEnd"
        @pointercancel="onPanEnd"
      >
        <img :src="props.src" :alt="props.title" :style="{ transform }" draggable="false" />

        <div class="dock" @pointerdown.stop @dblclick.stop>
          <button class="dock-btn" type="button" title="Allunya" @click="zoomAt(scale / 1.4)">−</button>
          <button class="dock-btn pct" type="button" title="Ajusta" @click="reset">{{ percent }}</button>
          <button class="dock-btn" type="button" title="Apropa" @click="zoomAt(scale * 1.4)">+</button>
          <span class="dock-sep" />
          <button class="dock-btn" type="button" title="Gira 90°" @click="rotate">
            <AppIcon name="refresh" :size="13" />
          </button>
        </div>
      </div>

      <span
        class="resize"
        title="Arrossega per canviar la mida"
        @pointerdown="startDrag($event, 'size')"
        @pointermove="moveDrag"
        @pointerup="endDrag"
        @pointercancel="endDrag"
      />
    </aside>
  </Teleport>
</template>

<style scoped>
.peek {
  position: fixed;
  z-index: 50;
  display: grid;
  grid-template-rows: auto minmax(0, 1fr);
  background: var(--surface-0);
  border: 1px solid var(--line);
  border-radius: var(--r-lg);
  box-shadow:
    0 1px 2px rgb(28 25 23 / 0.06),
    0 12px 32px -6px rgb(28 25 23 / 0.22),
    0 0 0 1px rgb(28 25 23 / 0.03);
  overflow: hidden;
  animation: peek-in 0.16s ease-out;
}

@keyframes peek-in {
  from {
    opacity: 0;
    transform: translateY(6px) scale(0.985);
  }
}

.peek-head {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 6px 6px 6px 8px;
  border-bottom: 1px solid var(--line);
  cursor: grab;
  user-select: none;
  touch-action: none;
}

.peek-head:active {
  cursor: grabbing;
}

/* Six dots: "you can hold this". */
.grip {
  flex: none;
  width: 6px;
  height: 14px;
  background-image: radial-gradient(circle, var(--ink-400) 1px, transparent 1.2px);
  background-size: 3px 4.7px;
  opacity: 0.7;
}

.peek-title {
  display: grid;
  flex: 1;
  min-width: 0;
  line-height: 1.25;
  font-size: var(--text-sm);
}

.peek-title span {
  font-size: var(--text-xs);
  color: var(--ink-500);
}

.icon-btn {
  display: inline-grid;
  place-items: center;
  flex: none;
  width: 26px;
  height: 26px;
  border: 0;
  border-radius: var(--r-sm);
  background: transparent;
  color: var(--ink-500);
  cursor: pointer;
}

.icon-btn:hover {
  background: var(--surface-2);
  color: var(--ink-900, var(--ink-700));
}

.stage {
  position: relative;
  display: grid;
  place-items: center;
  overflow: hidden;
  background:
    radial-gradient(circle at 1px 1px, rgb(28 25 23 / 0.07) 1px, transparent 0) 0 0 / 14px 14px,
    var(--surface-1);
  touch-action: none;
  user-select: none;
  cursor: zoom-in;
}

.stage.zoomed {
  cursor: grab;
}

.stage.zoomed.panning {
  cursor: grabbing;
}

.stage img {
  max-width: calc(100% - 28px);
  max-height: calc(100% - 28px);
  object-fit: contain;
  border-radius: 2px;
  transform-origin: center;
  transition: transform 0.08s ease-out;
  will-change: transform;
  box-shadow:
    0 1px 2px rgb(0 0 0 / 0.08),
    0 6px 18px rgb(0 0 0 / 0.12);
}

.stage.panning img {
  transition: none;
}

/* Floating controls, out of the way until the pointer is over the picture. */
.dock {
  position: absolute;
  left: 50%;
  bottom: 12px;
  display: flex;
  align-items: center;
  gap: 1px;
  padding: 3px;
  border-radius: var(--r-md);
  background: rgb(28 25 23 / 0.78);
  backdrop-filter: blur(8px);
  box-shadow: 0 4px 14px rgb(0 0 0 / 0.18);
  transform: translate(-50%, 4px);
  opacity: 0;
  transition:
    opacity 0.14s ease,
    transform 0.14s ease;
  cursor: default;
}

.stage:hover .dock,
.dock:focus-within {
  opacity: 1;
  transform: translate(-50%, 0);
}

.dock-btn {
  display: inline-grid;
  place-items: center;
  min-width: 26px;
  height: 26px;
  padding: 0 6px;
  border: 0;
  border-radius: var(--r-sm);
  background: transparent;
  color: #eef3fb;
  font-size: var(--text-base);
  line-height: 1;
  cursor: pointer;
}

.dock-btn:hover {
  background: rgb(255 255 255 / 0.14);
}

.pct {
  min-width: 46px;
  font-size: var(--text-xs);
  font-variant-numeric: tabular-nums;
}

.dock-sep {
  width: 1px;
  height: 16px;
  margin: 0 2px;
  background: rgb(255 255 255 / 0.2);
}

.pdf {
  width: 100%;
  height: 100%;
  border: 0;
  background: var(--surface-1);
}

.peek-empty {
  display: grid;
  place-items: center;
  align-content: center;
  gap: 10px;
  background: var(--surface-1);
  font-size: var(--text-sm);
  color: var(--ink-500);
}

.shimmer {
  width: 120px;
  height: 150px;
  border-radius: var(--r-sm);
  background: linear-gradient(100deg, var(--surface-2) 40%, var(--surface-0) 50%, var(--surface-2) 60%) 0 0 / 300% 100%;
  animation: shimmer 1.1s linear infinite;
}

@keyframes shimmer {
  to {
    background-position: -150% 0;
  }
}

.resize {
  position: absolute;
  right: 0;
  bottom: 0;
  width: 16px;
  height: 16px;
  cursor: nwse-resize;
  touch-action: none;
  background: linear-gradient(135deg, transparent 50%, var(--ink-400) 50%, var(--ink-400) 56%, transparent 56%, transparent 70%, var(--ink-400) 70%, var(--ink-400) 76%, transparent 76%);
  opacity: 0.55;
}

@media (max-width: 1000px) {
  .peek {
    left: 8px !important;
    right: 8px;
    top: auto !important;
    bottom: 8px;
    width: auto !important;
    height: 62vh !important;
  }

  .peek-head {
    cursor: default;
  }

  .resize {
    display: none;
  }
}
</style>
