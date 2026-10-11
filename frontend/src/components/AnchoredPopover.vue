<script setup lang="ts">
/**
 * A small panel that floats under the thing that opened it — over the page,
 * never pushing it around. Closes on Esc, on a click outside, and when its
 * anchor scrolls out of reach.
 */
import { nextTick, onBeforeUnmount, onMounted, ref } from 'vue'

const props = withDefaults(
  defineProps<{ anchor: HTMLElement | null; width?: number; label?: string }>(),
  { width: 248, label: undefined },
)
const emit = defineEmits<{ close: [] }>()

const panel = ref<HTMLElement | null>(null)
const position = ref({ top: 0, left: 0, maxHeight: 400 })

function place() {
  const rect = props.anchor?.getBoundingClientRect()
  if (!rect) return
  const margin = 8
  const below = window.innerHeight - rect.bottom - margin
  const above = rect.top - margin
  // Open upward only when there is clearly more room there.
  const up = below < 240 && above > below
  const maxHeight = Math.min(420, (up ? above : below) - 6)
  const height = Math.min(panel.value?.scrollHeight ?? 0, maxHeight)
  position.value = {
    top: up ? rect.top - 6 - height : rect.bottom + 6,
    left: Math.min(Math.max(margin, rect.left), window.innerWidth - props.width - margin),
    maxHeight,
  }
}

function onPointer(event: PointerEvent) {
  const target = event.target as Node
  if (!panel.value?.contains(target) && !props.anchor?.contains(target)) emit('close')
}
function onKey(event: KeyboardEvent) {
  if (event.key !== 'Escape') return
  event.stopPropagation()
  emit('close')
  props.anchor?.focus()
}

onMounted(async () => {
  place()
  await nextTick()
  place()
  window.addEventListener('pointerdown', onPointer, true)
  window.addEventListener('keydown', onKey, true)
  window.addEventListener('resize', place)
  window.addEventListener('scroll', place, { capture: true, passive: true })
})
onBeforeUnmount(() => {
  window.removeEventListener('pointerdown', onPointer, true)
  window.removeEventListener('keydown', onKey, true)
  window.removeEventListener('resize', place)
  window.removeEventListener('scroll', place, { capture: true })
})

defineExpose({ place })
</script>

<template>
  <Teleport to="body">
    <div
      ref="panel"
      class="popover"
      role="dialog"
      :aria-label="label"
      :style="{
        top: `${position.top}px`,
        left: `${position.left}px`,
        width: `${width}px`,
        maxHeight: `${position.maxHeight}px`,
      }"
    >
      <slot />
    </div>
  </Teleport>
</template>

<style scoped>
.popover {
  position: fixed;
  z-index: 95;
  max-width: calc(100vw - 16px);
  overflow: auto;
  overscroll-behavior: contain;
  background: var(--surface-0);
  border: 1px solid var(--line);
  border-radius: var(--r-lg);
  box-shadow: var(--shadow-lg);
  animation: pop 0.12s ease-out;
}

@keyframes pop {
  from {
    opacity: 0;
    transform: translateY(-3px);
  }
}
</style>
