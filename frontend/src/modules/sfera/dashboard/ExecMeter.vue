<script setup lang="ts">
/**
 * Executed against budgeted. Blue for income, coral for spending; past 100 %
 * the fill turns red and the label says so, so it never rests on colour alone.
 */
import { computed } from 'vue'
import { pctLabel } from './format'

const props = withDefaults(defineProps<{ value: number; total: number; kind: 'I' | 'D'; label?: boolean }>(), { label: true })
const ratio = computed(() => (props.total > 0 ? props.value / props.total : props.value > 0 ? Infinity : 0))
const over = computed(() => ratio.value > 1.00005)
const text = computed(() => (!Number.isFinite(ratio.value) ? 'Sense pressupost' : pctLabel(ratio.value)))
</script>

<template>
  <span class="meter" :class="[kind === 'I' ? 'income' : 'expense', { over }]">
    <span class="track" role="meter" :aria-valuenow="Math.round(Math.min(ratio, 9.99) * 100)" aria-valuemin="0" aria-valuemax="100" :aria-label="text">
      <span class="fill" :style="{ width: `${Math.min(1, Number.isFinite(ratio) ? ratio : 1) * 100}%` }" />
    </span>
    <span v-if="label" class="value">{{ over && Number.isFinite(ratio) ? `${text} · excés` : text }}</span>
  </span>
</template>

<style scoped>
.meter { display: inline-flex; align-items: center; gap: 8px; width: 100%; min-width: 0; }
.track { position: relative; flex: 1; min-width: 48px; height: 6px; border-radius: var(--r-full); overflow: hidden; }
.income .track { background: #e3ecfb; }
.expense .track { background: #f8e6dd; }
.fill { display: block; height: 100%; border-radius: inherit; }
.income .fill { background: #5b8de6; }
.expense .fill { background: #d9774b; }
.over .track { background: var(--danger-100); }
.over .fill { background: var(--danger-600); }
.value { flex: none; min-width: 38px; text-align: right; font-size: var(--text-sm); color: var(--ink-500); font-variant-numeric: tabular-nums; }
.over .value { color: var(--danger-700); font-weight: 600; }
</style>
