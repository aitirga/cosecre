<script setup lang="ts">
import { computed } from 'vue'

import { CA } from '../strings'

const props = defineProps<{ used: number; budget: number }>()

const share = computed(() =>
  props.budget > 0 ? Math.min(100, Math.round((props.used / props.budget) * 100)) : 0,
)

/* Gold from three-quarters spent, red once it is gone. `--gold-500` is a
   graphics-only step in the base system, which is exactly what a bar is. */
const tone = computed(() => (share.value >= 100 ? 'over' : share.value >= 75 ? 'warn' : ''))
</script>

<template>
  <div class="budget">
    <div class="progress" :class="tone">
      <span :style="{ width: share + '%' }" />
    </div>
    <span class="reading">{{ CA.chat.budget(used, budget) }}</span>
  </div>
</template>

<style scoped>
.budget {
  display: grid;
  gap: 3px;
  min-width: 140px;
}

.reading {
  font-size: var(--text-xs);
  color: var(--ink-400);
  text-align: right;
}

.progress.warn > span {
  background: var(--gold-500);
}

.progress.over > span {
  background: var(--aim-red-700);
}
</style>
