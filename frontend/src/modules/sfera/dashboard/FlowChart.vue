<script setup lang="ts">
/**
 * Money in (up, blue) and out (down, coral) of the centre's banks and cash
 * boxes per month, on one axis around zero. Hovering a month shows both and the net.
 */
import { computed, ref } from 'vue'
import type { SferaMonth } from '../../../sfera/dashboard'
import { euro, euroTick, monthLabel, monthTick, niceTicks } from './format'
import { useWidth } from './useWidth'

const props = defineProps<{ months: SferaMonth[] }>()
const box = ref<HTMLElement | null>(null)
const width = useWidth(box)
const H = 200, M = { top: 10, right: 12, bottom: 22, left: 58 }
const hover = ref<number | null>(null)

const ticks = computed(() => niceTicks(-Math.max(1, ...props.months.map(m => m.paid)), Math.max(1, ...props.months.map(m => m.collected))))
const lo = computed(() => ticks.value[0]), hi = computed(() => ticks.value[ticks.value.length - 1])
const y = (v: number) => M.top + (1 - (v - lo.value) / (hi.value - lo.value)) * (H - M.top - M.bottom)
const band = computed(() => (width.value - M.left - M.right) / Math.max(1, props.months.length))
const barW = computed(() => Math.min(22, band.value * 0.56))
const bars = computed(() => props.months.map((m, i) => {
  const cx = M.left + band.value * (i + 0.5)
  return { ...m, cx, x: cx - barW.value / 2, up: y(m.collected), down: y(-m.paid), zero: y(0) }
}))
const active = computed(() => (hover.value === null ? null : bars.value[hover.value]))
// Rounded at the data end, square at the baseline; 2px of surface left either side of zero.
function column(x: number, w: number, from: number, to: number) {
  const h = Math.abs(to - from)
  if (h < 0.5) return ''
  const r = Math.min(4, h, w / 2), up = to < from, s = up ? 1 : -1
  const base = from - s * 1
  return `M${x},${base}V${to + s * r}Q${x},${to} ${x + r},${to}H${x + w - r}Q${x + w},${to} ${x + w},${to + s * r}V${base}Z`
}
</script>

<template>
  <div ref="box" class="chart">
    <ul class="legend" aria-hidden="true">
      <li><i class="in" />Cobraments</li>
      <li><i class="out" />Pagaments</li>
    </ul>
    <svg :width="width" :height="H" role="img" aria-label="Cobraments i pagaments per mes. Detall a la taula de moviments." @pointerleave="hover = null">
      <g class="grid">
        <template v-for="t in ticks" :key="t">
          <line :x1="M.left" :x2="width - M.right" :y1="y(t)" :y2="y(t)" :class="{ zero: t === 0 }" />
          <text :x="M.left - 8" :y="y(t)" dy="0.32em" text-anchor="end">{{ euroTick(Math.abs(t)) }}</text>
        </template>
      </g>
      <g v-for="(b, i) in bars" :key="b.month" :class="{ dim: hover !== null && hover !== i }">
        <path :d="column(b.x, barW, b.zero, b.up)" class="in" />
        <path :d="column(b.x, barW, b.zero, b.down)" class="out" />
        <text :x="b.cx" :y="H - 6" text-anchor="middle" class="tick">{{ monthTick(b.month) }}</text>
        <rect :x="b.cx - band / 2" :y="0" :width="band" :height="H" fill="transparent" @pointerenter="hover = i" />
      </g>
    </svg>
    <div v-if="active" class="tip" :style="{ left: `${Math.min(Math.max(active.cx - 90, 0), width - 190)}px`, top: '28px' }">
      <span class="tip-title">{{ monthLabel(active.month) }}</span>
      <span><i class="in" />Cobraments <strong>{{ euro(active.collected) }}</strong></span>
      <span><i class="out" />Pagaments <strong>{{ euro(active.paid) }}</strong></span>
      <span class="net">Net <strong>{{ euro(active.collected - active.paid) }}</strong></span>
    </div>
  </div>
</template>

<style scoped>
.chart { position: relative; min-width: 0; }
svg { display: block; }
.legend { display: flex; gap: 14px; margin: 0 0 6px; padding: 0; list-style: none; font-size: var(--text-sm); color: var(--ink-500); }
.legend li, .tip span { display: flex; align-items: center; gap: 6px; }
i { display: inline-block; width: 10px; height: 10px; border-radius: 2px; }
i.in, path.in { background: #5b8de6; fill: #5b8de6; }
i.out, path.out { background: #d9774b; fill: #d9774b; }
.grid line { stroke: var(--line); stroke-width: 1; }
.grid line.zero { stroke: var(--line-strong); }
.grid text, .tick { fill: var(--ink-400); font-size: 11px; font-variant-numeric: tabular-nums; }
g.dim path { opacity: 0.35; }
.tip {
  position: absolute; pointer-events: none; display: grid; gap: 3px; min-width: 190px;
  padding: 7px 10px; background: var(--surface-0); border: 1px solid var(--line-strong);
  border-radius: var(--r-md); box-shadow: var(--shadow-md); font-size: var(--text-sm); color: var(--ink-500);
}
.tip-title { color: var(--ink-700); font-weight: 600; text-transform: capitalize; }
.tip strong { margin-left: auto; color: var(--ink-900); font-variant-numeric: tabular-nums; }
.tip .net { border-top: 1px solid var(--line); padding-top: 3px; }
</style>
