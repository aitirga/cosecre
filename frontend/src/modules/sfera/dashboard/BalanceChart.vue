<script setup lang="ts">
/**
 * Treasury balance through the year: one series, a step line (the balance only
 * moves when money does) over a 10 % wash, with a crosshair and tooltip.
 */
import { computed, ref } from 'vue'
import type { SferaBalancePoint } from '../../../sfera/dashboard'
import { dayLabel, euro, euroTick, monthTick, niceTicks } from './format'
import { useWidth } from './useWidth'

const props = defineProps<{ series: SferaBalancePoint[]; year: number }>()
const box = ref<HTMLElement | null>(null)
const width = useWidth(box)
const H = 190, M = { top: 12, right: 16, bottom: 22, left: 58 }
const hover = ref<number | null>(null)

const t0 = computed(() => Date.UTC(props.year, 0, 1))
const t1 = computed(() => Date.UTC(props.year + 1, 0, 1))
const ms = (iso: string) => Date.parse(`${iso}T00:00:00Z`)
const ticks = computed(() => {
  const values = props.series.map(p => p.balance)
  return niceTicks(Math.min(0, ...values), Math.max(...values, 1))
})
const x = (t: number) => M.left + ((t - t0.value) / (t1.value - t0.value)) * (width.value - M.left - M.right)
const y = (v: number) => {
  const lo = ticks.value[0], hi = ticks.value[ticks.value.length - 1]
  return M.top + (1 - (v - lo) / (hi - lo)) * (H - M.top - M.bottom)
}
const points = computed(() => props.series.map(p => ({ ...p, px: x(ms(p.date)), py: y(p.balance) })))
const line = computed(() => points.value.reduce((d, p, i) => d + (i === 0 ? `M${p.px},${p.py}` : `H${p.px}V${p.py}`), ''))
const area = computed(() => {
  const ps = points.value
  if (!ps.length) return ''
  return `${line.value}H${ps[ps.length - 1].px}V${y(Math.max(0, ticks.value[0]))}H${ps[0].px}Z`
})
const months = computed(() => Array.from({ length: 12 }, (_, m) => ({ key: `${props.year}-${String(m + 1).padStart(2, '0')}`, px: x(Date.UTC(props.year, m, 1)) })))
const last = computed(() => points.value[points.value.length - 1])
const active = computed(() => (hover.value === null ? null : points.value[hover.value]))

function move(event: PointerEvent) {
  const rect = (event.currentTarget as SVGElement).getBoundingClientRect()
  const px = event.clientX - rect.left
  let best = -1
  // The step holds a value until the next movement, so the point to show is the last one at or before the cursor.
  points.value.forEach((p, i) => { if (p.px <= px) best = i })
  hover.value = best >= 0 ? best : null
}
</script>

<template>
  <div ref="box" class="chart">
    <svg :width="width" :height="H" role="img" :aria-label="`Saldo de tresoreria durant ${year}. Saldo final ${last ? euro(last.balance) : ''}.`" @pointermove="move" @pointerleave="hover = null">
      <g class="grid">
        <template v-for="t in ticks" :key="t">
          <line :x1="M.left" :x2="width - M.right" :y1="y(t)" :y2="y(t)" />
          <text :x="M.left - 8" :y="y(t)" dy="0.32em" text-anchor="end">{{ euroTick(t) }}</text>
        </template>
        <text v-for="m in months" :key="m.key" :x="m.px + 2" :y="H - 6">{{ monthTick(m.key) }}</text>
      </g>
      <path :d="area" class="area" />
      <path :d="line" class="line" />
      <circle v-if="last" :cx="last.px" :cy="last.py" r="4" class="dot" />
      <template v-if="active">
        <line :x1="active.px" :x2="active.px" :y1="M.top" :y2="H - M.bottom" class="cross" />
        <circle :cx="active.px" :cy="active.py" r="4" class="dot" />
      </template>
    </svg>
    <div v-if="active" class="tip" :style="{ left: `${Math.min(active.px + 12, width - 180)}px`, top: `${Math.max(active.py - 46, 0)}px` }">
      <span>{{ dayLabel(active.date) }}</span>
      <strong>{{ euro(active.balance) }}</strong>
    </div>
  </div>
</template>

<style scoped>
.chart { position: relative; min-width: 0; }
svg { display: block; touch-action: none; }
.grid line { stroke: var(--line); stroke-width: 1; }
.grid text { fill: var(--ink-400); font-size: 11px; font-variant-numeric: tabular-nums; }
.area { fill: #5b8de6; opacity: 0.1; }
.line { fill: none; stroke: #3f6fce; stroke-width: 2; stroke-linejoin: round; stroke-linecap: round; }
.dot { fill: #3f6fce; stroke: var(--surface-0); stroke-width: 2; }
.cross { stroke: var(--line-strong); stroke-width: 1; }
.tip {
  position: absolute; pointer-events: none; display: grid; gap: 2px; min-width: 150px;
  padding: 6px 9px; background: var(--surface-0); border: 1px solid var(--line-strong);
  border-radius: var(--r-md); box-shadow: var(--shadow-md); font-size: var(--text-sm); color: var(--ink-500);
}
.tip strong { color: var(--ink-900); font-size: var(--text-md); font-variant-numeric: tabular-nums; }
</style>
