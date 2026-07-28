<script setup lang="ts">
/**
 * A plot, or an honest explanation of why there isn't one.
 *
 * The model will occasionally emit an expression the parser rejects. Validating
 * up front — rather than letting the renderer throw mid-render — keeps the
 * failure local and legible: the teacher sees the spec that came back and a
 * button to ask for another, never a blank box or a broken page.
 */
import { computed } from 'vue'

import AppIcon from '../../../components/AppIcon.vue'
import { CA } from '../strings'
import type { AimPlotSpec } from '../types'
import AimPlot from './AimPlot.vue'
import { compileExpression } from './expression'

const props = defineProps<{ spec: AimPlotSpec; regenerable?: boolean }>()
defineEmits<{ regenerate: [] }>()

const problem = computed(() => {
  if (props.spec.kind !== 'function') return null
  for (const series of props.spec.series) {
    try {
      compileExpression(series.expression)
    } catch (error) {
      return `${series.expression} — ${(error as Error).message}`
    }
  }
  return null
})
</script>

<template>
  <AimPlot v-if="!problem" :spec="spec" />
  <div v-else class="notice-error broken">
    <p>{{ problem }}</p>
    <button
      v-if="regenerable"
      class="btn btn-outline btn-sm"
      type="button"
      @click="$emit('regenerate')"
    >
      <AppIcon name="refresh" :size="14" />
      {{ CA.wizard.regeneratePlot }}
    </button>
  </div>
</template>

<style scoped>
.broken {
  display: grid;
  gap: 8px;
  justify-items: start;
}

.broken p {
  font-family: var(--font-mono);
  font-size: var(--text-xs);
  word-break: break-all;
}
</style>
