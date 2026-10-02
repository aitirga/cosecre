<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'

import AppIcon from './AppIcon.vue'

/**
 * Full-screen viewer for a document photo: wheel or pinch to zoom towards the
 * pointer, drag to pan, double-click to toggle, Esc to close. Built for reading
 * the small print of a crumpled receipt, so zoom goes well past 100 %.
 */
const props = defineProps<{ src: string; alt?: string }>()
const emit = defineEmits<{ close: [] }>()

const MIN = 1
const MAX = 8
const scale = ref(1)
const tx = ref(0)
const ty = ref(0)
const stage = ref<HTMLElement | null>(null)
const dragging = ref(false)

const clamp = (value: number, low: number, high: number) => Math.min(high, Math.max(low, value))
const percent = computed(() => `${Math.round(scale.value * 100)} %`)
const transform = computed(
  () => `translate(${tx.value}px, ${ty.value}px) scale(${scale.value})`,
)

/** Zoom to `next`, keeping the point (x, y) — in stage pixels — still. */
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

function reset() {
  scale.value = 1
  tx.value = 0
  ty.value = 0
}

function onWheel(event: WheelEvent) {
  event.preventDefault()
  zoomAt(scale.value * Math.exp(-event.deltaY * 0.0018), event.clientX, event.clientY)
}

function onDoubleClick(event: MouseEvent) {
  if (scale.value > 1.05) reset()
  else zoomAt(2.5, event.clientX, event.clientY)
}

// ── Pointers: one drags, two pinch ────────────────────────────────────────────
const pointers = new Map<number, { x: number; y: number }>()
let pinchStart: { distance: number; scale: number } | null = null

function distance() {
  const [a, b] = [...pointers.values()]
  return a && b ? Math.hypot(a.x - b.x, a.y - b.y) : 0
}

function onPointerDown(event: PointerEvent) {
  ;(event.currentTarget as HTMLElement).setPointerCapture(event.pointerId)
  pointers.set(event.pointerId, { x: event.clientX, y: event.clientY })
  dragging.value = true
  if (pointers.size === 2) pinchStart = { distance: distance(), scale: scale.value }
}

function onPointerMove(event: PointerEvent) {
  const previous = pointers.get(event.pointerId)
  if (!previous) return
  const current = { x: event.clientX, y: event.clientY }
  pointers.set(event.pointerId, current)
  if (pointers.size === 2 && pinchStart) {
    const [a, b] = [...pointers.values()]
    zoomAt(pinchStart.scale * (distance() / pinchStart.distance), (a.x + b.x) / 2, (a.y + b.y) / 2)
  } else if (pointers.size === 1 && scale.value > 1) {
    tx.value += current.x - previous.x
    ty.value += current.y - previous.y
  }
}

function onPointerUp(event: PointerEvent) {
  pointers.delete(event.pointerId)
  if (pointers.size < 2) pinchStart = null
  if (!pointers.size) dragging.value = false
}

function onKey(event: KeyboardEvent) {
  if (event.key === 'Escape') emit('close')
  else if (event.key === '+' || event.key === '=') zoomAt(scale.value * 1.4)
  else if (event.key === '-') zoomAt(scale.value / 1.4)
  else if (event.key === '0') reset()
}

onMounted(() => {
  window.addEventListener('keydown', onKey)
  document.body.style.overflow = 'hidden'
})
onBeforeUnmount(() => {
  window.removeEventListener('keydown', onKey)
  document.body.style.overflow = ''
})
</script>

<template>
  <Teleport to="body">
    <div class="viewer" role="dialog" aria-modal="true" :aria-label="props.alt || 'Imatge'">
      <div
        ref="stage"
        class="stage"
        :class="{ dragging, zoomed: scale > 1 }"
        @wheel="onWheel"
        @dblclick="onDoubleClick"
        @pointerdown="onPointerDown"
        @pointermove="onPointerMove"
        @pointerup="onPointerUp"
        @pointercancel="onPointerUp"
        @click.self="scale === 1 && emit('close')"
      >
        <img :src="props.src" :alt="props.alt" :style="{ transform }" draggable="false" />
      </div>

      <div class="toolbar" @click.stop>
        <button class="tool" type="button" title="Allunya (−)" @click="zoomAt(scale / 1.4)">
          <span aria-hidden="true">−</span>
          <span class="sr-only">Allunya</span>
        </button>
        <button class="tool percent" type="button" title="Mida ajustada (0)" @click="reset">
          {{ percent }}
        </button>
        <button class="tool" type="button" title="Apropa (+)" @click="zoomAt(scale * 1.4)">
          <span aria-hidden="true">+</span>
          <span class="sr-only">Apropa</span>
        </button>
        <span class="divider" />
        <a class="tool" :href="props.src" target="_blank" rel="noopener" title="Obre en una pestanya nova">
          <AppIcon name="external" :size="15" />
        </a>
        <button class="tool" type="button" title="Tanca (Esc)" @click="emit('close')">
          <AppIcon name="close" :size="15" />
          <span class="sr-only">Tanca</span>
        </button>
      </div>

      <p class="help">Roda o pessic per fer zoom · arrossega per moure · doble clic per apropar</p>
    </div>
  </Teleport>
</template>

<style scoped>
.viewer {
  position: fixed;
  inset: 0;
  z-index: 100;
  background: rgba(20, 17, 15, 0.94);
}

.stage {
  position: absolute;
  inset: 0;
  display: grid;
  place-items: center;
  overflow: hidden;
  touch-action: none;
  cursor: zoom-in;
  user-select: none;
}

.stage.zoomed {
  cursor: grab;
}

.stage.zoomed.dragging {
  cursor: grabbing;
}

.stage img {
  max-width: 94vw;
  max-height: 88vh;
  object-fit: contain;
  transform-origin: center;
  transition: transform 0.06s linear;
  will-change: transform;
  box-shadow: 0 10px 40px rgba(0, 0, 0, 0.4);
}

.stage.dragging img {
  transition: none;
}

.toolbar {
  position: absolute;
  top: 14px;
  left: 50%;
  transform: translateX(-50%);
  display: flex;
  align-items: center;
  gap: 2px;
  padding: 4px;
  border-radius: var(--r-lg);
  background: rgba(28, 25, 23, 0.86);
  box-shadow: var(--shadow-md);
}

.tool {
  display: inline-grid;
  place-items: center;
  min-width: 32px;
  height: 32px;
  padding: 0 8px;
  border: 0;
  border-radius: var(--r-md);
  background: transparent;
  color: #f5efe6;
  font-size: var(--text-lg);
  line-height: 1;
  cursor: pointer;
}

.tool:hover {
  background: rgba(255, 255, 255, 0.12);
}

.percent {
  min-width: 64px;
  font-size: var(--text-sm);
  font-variant-numeric: tabular-nums;
}

.divider {
  width: 1px;
  height: 20px;
  margin: 0 4px;
  background: rgba(255, 255, 255, 0.18);
}

.help {
  position: absolute;
  bottom: 12px;
  left: 0;
  right: 0;
  margin: 0;
  text-align: center;
  font-size: var(--text-sm);
  color: rgba(245, 239, 230, 0.6);
  pointer-events: none;
}

@media (hover: none) {
  .help {
    display: none;
  }
}
</style>
