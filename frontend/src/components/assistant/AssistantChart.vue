<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'

import type { AssistantBlock } from '../../api/types'
import AppIcon from '../AppIcon.vue'
import { formatNumber, SERIES_COLORS } from './format'

type Chart = Extract<AssistantBlock, { type: 'chart' }>

/**
 * A chart the Assistent drew from a query.
 *
 * Plain SVG sized to its box: one axis, thin marks, a recessive grid, a legend
 * from two series up, a tooltip on every mark and the numbers a click away in
 * a table — the colours are a signal, never the only way to read it.
 */
const props = defineProps<{ chart: Chart }>()

const box = ref<HTMLElement | null>(null)
const width = ref(640)
const hovered = ref<number | null>(null)
const pointer = ref({ x: 0, y: 0 })
const asTable = ref(false)
let observer: ResizeObserver | null = null

onMounted(() => {
  if (!box.value) return
  width.value = box.value.clientWidth || 640
  observer = new ResizeObserver(([entry]) => {
    if (entry) width.value = Math.max(260, entry.contentRect.width)
  })
  observer.observe(box.value)
})
onBeforeUnmount(() => observer?.disconnect())

const kind = computed(() => props.chart.kind)
const labels = computed(() => props.chart.labels)
const series = computed(() => props.chart.series.slice(0, SERIES_COLORS.length))
const horizontal = computed(() => kind.value === 'bar' && props.chart.horizontal)
const stacked = computed(() => props.chart.stacked && ['bar', 'area'].includes(kind.value))

function color(index: number) {
  return SERIES_COLORS[index % SERIES_COLORS.length]
}

function value(v: number | null | undefined, compact = false) {
  return formatNumber(v, props.chart.unit, compact)
}

// ── Scale ────────────────────────────────────────────────────────────────────

function niceStep(span: number, count: number) {
  const raw = span / Math.max(1, count)
  const power = 10 ** Math.floor(Math.log10(raw || 1))
  const scaled = raw / power
  return (scaled <= 1 ? 1 : scaled <= 2 ? 2 : scaled <= 2.5 ? 2.5 : scaled <= 5 ? 5 : 10) * power
}

/** Every value a mark reaches, stacks summed per sign. */
const extent = computed(() => {
  const values: number[] = [0]
  if (stacked.value) {
    labels.value.forEach((_, i) => {
      let up = 0
      let down = 0
      for (const s of series.value) {
        const v = s.values[i] ?? 0
        if (v >= 0) up += v
        else down += v
      }
      values.push(up, down)
    })
  } else {
    for (const s of series.value) for (const v of s.values) if (v != null) values.push(v)
  }
  const min = Math.min(...values)
  const max = Math.max(...values)
  const step = niceStep(max - min || Math.abs(max) || 1, 4)
  const lo = Math.floor(min / step) * step
  const hi = Math.ceil(max / step) * step || step
  const ticks: number[] = []
  for (let t = lo; t <= hi + step / 2; t += step) ticks.push(Number(t.toFixed(10)))
  return { lo, hi, ticks }
})

// ── Layout ───────────────────────────────────────────────────────────────────

const height = computed(() =>
  horizontal.value ? Math.min(560, 40 + labels.value.length * 28) : kind.value === 'pie' ? 240 : 260,
)
const labelWidth = computed(() =>
  horizontal.value ? Math.min(180, Math.max(60, ...labels.value.map((l) => l.length * 6.4))) : 0,
)
const pad = computed(() => ({
  top: 12,
  right: 16,
  bottom: horizontal.value ? 24 : 34,
  left: horizontal.value ? labelWidth.value + 8 : 56,
}))
const plotW = computed(() => Math.max(40, width.value - pad.value.left - pad.value.right))
const plotH = computed(() => Math.max(40, height.value - pad.value.top - pad.value.bottom))

/** Position along the value axis. */
function scale(v: number) {
  const { lo, hi } = extent.value
  const t = (v - lo) / (hi - lo || 1)
  return horizontal.value ? pad.value.left + t * plotW.value : pad.value.top + plotH.value - t * plotH.value
}

const band = computed(() => (horizontal.value ? plotH.value : plotW.value) / Math.max(1, labels.value.length))

/** Centre of category `i` along the category axis. */
function center(i: number) {
  if (kind.value === 'line' || kind.value === 'area' || kind.value === 'scatter') {
    const n = labels.value.length
    return pad.value.left + (n <= 1 ? plotW.value / 2 : (i / (n - 1)) * plotW.value)
  }
  return (horizontal.value ? pad.value.top : pad.value.left) + band.value * (i + 0.5)
}

/** Which category labels fit under the axis without colliding. */
const shownLabels = computed(() => {
  const room = horizontal.value ? 18 : Math.max(...labels.value.map((l) => l.length * 6.2), 24) + 8
  const span = horizontal.value ? band.value : plotW.value / Math.max(1, labels.value.length)
  const every = Math.max(1, Math.ceil(room / Math.max(span, 1)))
  return new Set(labels.value.map((_, i) => i).filter((i) => i % every === 0 || i === labels.value.length - 1))
})

// ── Marks ────────────────────────────────────────────────────────────────────

interface Rect {
  x: number
  y: number
  w: number
  h: number
  fill: string
  i: number
  s: number
  /** Which end is the data end — it gets the rounded corners. */
  end: 'top' | 'bottom' | 'right' | 'left'
}

const bars = computed<Rect[]>(() => {
  if (kind.value !== 'bar') return []
  const count = series.value.length
  const thick = stacked.value ? Math.min(24, band.value * 0.6) : Math.min(24, (band.value * 0.72) / count)
  const rects: Rect[] = []
  labels.value.forEach((_, i) => {
    let up = 0
    let down = 0
    series.value.forEach((s, si) => {
      const v = s.values[i]
      if (v == null) return
      let from: number
      let to: number
      if (stacked.value) {
        from = v >= 0 ? up : down
        to = from + v
        if (v >= 0) up = to
        else down = to
      } else {
        from = 0
        to = v
      }
      const a = scale(from)
      const b = scale(to)
      const offset = stacked.value ? -thick / 2 : (si - count / 2) * thick
      // 2px of surface between neighbours, so touching bars read apart.
      const gap = count > 1 || stacked.value ? 1 : 0
      const c = center(i) + offset
      if (horizontal.value) {
        rects.push({
          x: Math.min(a, b) + (stacked.value ? gap : 0),
          y: c + (stacked.value ? 0 : gap),
          w: Math.max(0, Math.abs(b - a) - (stacked.value ? gap * 2 : 0)),
          h: Math.max(1, thick - (stacked.value ? 0 : gap * 2)),
          fill: color(si),
          i,
          s: si,
          end: v >= 0 ? 'right' : 'left',
        })
      } else {
        rects.push({
          x: c + (stacked.value ? 0 : gap),
          y: Math.min(a, b) + (stacked.value ? gap : 0),
          w: Math.max(1, thick - (stacked.value ? 0 : gap * 2)),
          h: Math.max(0, Math.abs(b - a) - (stacked.value ? gap * 2 : 0)),
          fill: color(si),
          i,
          s: si,
          end: v >= 0 ? 'top' : 'bottom',
        })
      }
    })
  })
  return rects
})

/** A bar with its data end rounded (4px) and its baseline square. */
function barPath(r: Rect) {
  const rad = Math.min(4, r.w / 2, r.h / 2)
  const { x, y, w, h } = r
  if (r.end === 'top')
    return `M${x},${y + h}V${y + rad}Q${x},${y} ${x + rad},${y}H${x + w - rad}Q${x + w},${y} ${x + w},${y + rad}V${y + h}Z`
  if (r.end === 'bottom')
    return `M${x},${y}V${y + h - rad}Q${x},${y + h} ${x + rad},${y + h}H${x + w - rad}Q${x + w},${y + h} ${x + w},${y + h - rad}V${y}Z`
  if (r.end === 'right')
    return `M${x},${y}H${x + w - rad}Q${x + w},${y} ${x + w},${y + rad}V${y + h - rad}Q${x + w},${y + h} ${x + w - rad},${y + h}H${x}Z`
  return `M${x + w},${y}H${x + rad}Q${x},${y} ${x},${y + rad}V${y + h - rad}Q${x},${y + h} ${x + rad},${y + h}H${x + w}Z`
}

const lines = computed(() => {
  if (!['line', 'area', 'scatter'].includes(kind.value)) return []
  const base = new Array(labels.value.length).fill(0) as number[]
  return series.value.map((s, si) => {
    const points = s.values.map((v, i) => {
      if (v == null) return null
      const from = stacked.value ? (base[i] ?? 0) : 0
      const to = from + v
      if (stacked.value) base[i] = to
      return { x: center(i), y: scale(to), y0: scale(from), i }
    })
    const valid = points.filter((p): p is NonNullable<typeof p> => p !== null)
    const d = valid.map((p, k) => `${k ? 'L' : 'M'}${p.x},${p.y}`).join('')
    const area =
      kind.value === 'area' && valid.length
        ? `${d}${[...valid].reverse().map((p) => `L${p.x},${p.y0}`).join('')}Z`
        : ''
    return { d, area, points: valid, color: color(si), s: si }
  })
})

const pie = computed(() => {
  if (kind.value !== 'pie') return []
  const values = (series.value[0]?.values ?? []).map((v) => Math.max(0, v ?? 0))
  const total = values.reduce((a, b) => a + b, 0) || 1
  const cx = width.value / 2 - (width.value > 480 ? 90 : 0)
  const cy = height.value / 2
  const r = Math.min(height.value / 2 - 8, 110)
  const inner = r * 0.6
  let angle = -Math.PI / 2
  return values.map((v, i) => {
    const sweep = (v / total) * Math.PI * 2
    const a0 = angle
    const a1 = angle + Math.max(0, sweep - (values.length > 1 ? 0.02 : 0))
    angle += sweep
    const large = a1 - a0 > Math.PI ? 1 : 0
    const p = (a: number, rr: number) => `${cx + rr * Math.cos(a)},${cy + rr * Math.sin(a)}`
    const d =
      sweep >= Math.PI * 2 - 0.001
        ? `M${cx - r},${cy}a${r},${r} 0 1,0 ${r * 2},0a${r},${r} 0 1,0 ${-r * 2},0M${cx - inner},${cy}a${inner},${inner} 0 1,1 ${inner * 2},0a${inner},${inner} 0 1,1 ${-inner * 2},0`
        : `M${p(a0, r)}A${r},${r} 0 ${large} 1 ${p(a1, r)}L${p(a1, inner)}A${inner},${inner} 0 ${large} 0 ${p(a0, inner)}Z`
    return { d, i, color: color(i), share: v / total }
  })
})

// ── Hover ────────────────────────────────────────────────────────────────────

function onMove(event: MouseEvent) {
  const svg = event.currentTarget as SVGSVGElement
  const rect = svg.getBoundingClientRect()
  const x = ((event.clientX - rect.left) / rect.width) * width.value
  const y = ((event.clientY - rect.top) / rect.height) * height.value
  pointer.value = { x: event.clientX - rect.left, y: event.clientY - rect.top }
  if (kind.value === 'pie') return
  const n = labels.value.length
  if (!n) return
  let i: number
  if (kind.value === 'bar') {
    const along = horizontal.value ? y - pad.value.top : x - pad.value.left
    i = Math.floor(along / band.value)
  } else {
    i = n <= 1 ? 0 : Math.round(((x - pad.value.left) / plotW.value) * (n - 1))
  }
  hovered.value = i >= 0 && i < n ? i : null
}

function onPie(i: number, event: MouseEvent) {
  const svg = (event.currentTarget as SVGElement).ownerSVGElement
  const rect = svg?.getBoundingClientRect()
  if (rect) pointer.value = { x: event.clientX - rect.left, y: event.clientY - rect.top }
  hovered.value = i
}

const tooltip = computed(() => {
  const i = hovered.value
  if (i == null) return null
  if (kind.value === 'pie') {
    const v = series.value[0]?.values[i]
    const share = pie.value[i]?.share ?? 0
    return {
      title: labels.value[i] ?? '',
      rows: [{ name: series.value[0]?.name ?? '', value: `${value(v)} · ${(share * 100).toFixed(1).replace('.', ',')} %`, color: color(i) }],
    }
  }
  return {
    title: labels.value[i] ?? '',
    rows: series.value.map((s, si) => ({ name: s.name, value: value(s.values[i]), color: color(si) })),
  }
})

const tooltipStyle = computed(() => {
  const left = Math.min(pointer.value.x + 14, width.value - 200)
  return { left: `${Math.max(0, left)}px`, top: `${Math.max(0, pointer.value.y - 12)}px` }
})

const showLegend = computed(() => series.value.length > 1 || kind.value === 'pie')
const legend = computed(() =>
  kind.value === 'pie'
    ? labels.value.map((label, i) => ({ name: label, color: color(i) }))
    : series.value.map((s, si) => ({ name: s.name, color: color(si) })),
)
</script>

<template>
  <figure class="chart">
    <figcaption class="chart-head">
      <span class="chart-title">{{ chart.title }}</span>
      <span v-if="chart.y_label" class="chart-sub">{{ chart.y_label }}</span>
      <button class="btn btn-ghost btn-sm toggle" type="button" @click="asTable = !asTable">
        <AppIcon :name="asTable ? 'activity' : 'sheet'" :size="13" />
        {{ asTable ? 'Gràfic' : 'Dades' }}
      </button>
    </figcaption>

    <ul v-if="showLegend && !asTable" class="legend">
      <li v-for="(item, i) in legend" :key="i">
        <span class="key" :class="{ line: kind === 'line' }" :style="{ background: item.color }" />
        {{ item.name }}
      </li>
    </ul>

    <div v-show="!asTable" ref="box" class="plot">
      <svg
        :viewBox="`0 0 ${width} ${height}`"
        :width="width"
        :height="height"
        role="img"
        :aria-label="chart.title"
        @mousemove="onMove"
        @mouseleave="hovered = null"
      >
        <template v-if="kind !== 'pie'">
          <!-- Grid and value axis -->
          <g class="grid">
            <template v-for="tick in extent.ticks" :key="tick">
              <line
                v-if="!horizontal"
                :x1="pad.left"
                :x2="pad.left + plotW"
                :y1="scale(tick)"
                :y2="scale(tick)"
                :class="{ zero: tick === 0 }"
              />
              <line v-else :y1="pad.top" :y2="pad.top + plotH" :x1="scale(tick)" :x2="scale(tick)" :class="{ zero: tick === 0 }" />
              <text
                v-if="!horizontal"
                class="tick"
                :x="pad.left - 8"
                :y="scale(tick) + 4"
                text-anchor="end"
              >{{ value(tick, true) }}</text>
              <text v-else class="tick" :x="scale(tick)" :y="pad.top + plotH + 16" text-anchor="middle">{{ value(tick, true) }}</text>
            </template>
          </g>

          <!-- Category axis -->
          <g>
            <template v-for="(label, i) in labels" :key="i">
              <text
                v-if="shownLabels.has(i) && !horizontal"
                class="tick"
                :x="center(i)"
                :y="pad.top + plotH + 18"
                text-anchor="middle"
              >{{ label }}</text>
              <text
                v-else-if="horizontal"
                class="tick"
                :x="pad.left - 8"
                :y="center(i) + 4"
                text-anchor="end"
              >{{ label.length > 28 ? `${label.slice(0, 27)}…` : label }}</text>
            </template>
          </g>

          <!-- Hover band -->
          <rect
            v-if="hovered != null && kind === 'bar'"
            class="hover-band"
            :x="horizontal ? pad.left : center(hovered) - band / 2"
            :y="horizontal ? center(hovered) - band / 2 : pad.top"
            :width="horizontal ? plotW : band"
            :height="horizontal ? band : plotH"
          />
          <line
            v-if="hovered != null && kind !== 'bar'"
            class="crosshair"
            :x1="center(hovered)"
            :x2="center(hovered)"
            :y1="pad.top"
            :y2="pad.top + plotH"
          />

          <path v-for="(r, k) in bars" :key="`b${k}`" :d="barPath(r)" :fill="r.fill" :class="{ dim: hovered != null && hovered !== r.i }" />

          <template v-for="l in lines" :key="`l${l.s}`">
            <path v-if="l.area" :d="l.area" :fill="l.color" class="area" />
            <path v-if="kind !== 'scatter'" :d="l.d" :stroke="l.color" class="line" />
            <circle
              v-for="p in l.points"
              v-show="kind === 'scatter' || hovered === p.i || l.points.length === 1"
              :key="p.i"
              :cx="p.x"
              :cy="p.y"
              r="4"
              :fill="l.color"
              class="dot"
            />
          </template>
        </template>

        <template v-else>
          <path
            v-for="slice in pie"
            :key="slice.i"
            :d="slice.d"
            :fill="slice.color"
            fill-rule="evenodd"
            :class="{ dim: hovered != null && hovered !== slice.i }"
            @mousemove="onPie(slice.i, $event)"
          />
        </template>
      </svg>

      <div v-if="tooltip" class="tooltip" :style="tooltipStyle">
        <strong>{{ tooltip.title }}</strong>
        <div v-for="(row, k) in tooltip.rows" :key="k" class="tip-row">
          <span class="key" :style="{ background: row.color }" />
          <span class="tip-name">{{ row.name }}</span>
          <span class="tip-value">{{ row.value }}</span>
        </div>
      </div>
    </div>

    <div v-if="asTable" class="data">
      <table class="table">
        <thead>
          <tr>
            <th>{{ chart.x_label }}</th>
            <th v-for="s in series" :key="s.name" class="num">{{ s.name }}</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="(label, i) in labels" :key="i">
            <td>{{ label }}</td>
            <td v-for="s in series" :key="s.name" class="num">{{ value(s.values[i]) }}</td>
          </tr>
        </tbody>
      </table>
    </div>

    <p v-if="chart.note || chart.truncated" class="note">
      {{ chart.note }}<template v-if="chart.truncated"> Només es mostren els primers punts.</template>
    </p>
  </figure>
</template>

<style scoped>
.chart {
  margin: 0;
  padding: 12px 14px 10px;
  border: 1px solid var(--line);
  border-radius: var(--r-lg);
  background: var(--surface-0);
}

.chart-head {
  display: flex;
  align-items: baseline;
  gap: 8px;
  margin-bottom: 6px;
}

.chart-title {
  font-size: var(--text-base);
  font-weight: 600;
  color: var(--ink-900);
}

.chart-sub {
  font-size: var(--text-sm);
  color: var(--ink-400);
}

.toggle {
  margin-left: auto;
}

.legend {
  display: flex;
  flex-wrap: wrap;
  gap: 4px 14px;
  margin: 0 0 6px;
  padding: 0;
  list-style: none;
  font-size: var(--text-sm);
  color: var(--ink-500);
}

.legend li {
  display: inline-flex;
  align-items: center;
  gap: 6px;
}

.key {
  display: inline-block;
  width: 10px;
  height: 10px;
  border-radius: 2px;
  flex: none;
}

.key.line {
  height: 2px;
  width: 12px;
}

.plot {
  position: relative;
  width: 100%;
}

svg {
  display: block;
  width: 100%;
  height: auto;
  overflow: visible;
}

.grid line {
  stroke: var(--line);
  stroke-width: 1;
}

.grid line.zero {
  stroke: var(--line-strong);
}

.tick {
  font-size: 11px;
  fill: var(--ink-400);
  font-variant-numeric: tabular-nums;
}

.hover-band {
  fill: var(--surface-2);
}

.crosshair {
  stroke: var(--line-strong);
  stroke-width: 1;
}

.line {
  fill: none;
  stroke-width: 2;
  stroke-linejoin: round;
  stroke-linecap: round;
}

.area {
  opacity: 0.1;
}

.dot {
  stroke: var(--surface-0);
  stroke-width: 2;
}

.dim {
  opacity: 0.45;
}

path {
  transition: opacity 0.1s ease;
}

.tooltip {
  position: absolute;
  z-index: 2;
  min-width: 150px;
  max-width: 240px;
  padding: 7px 9px;
  border: 1px solid var(--line);
  border-radius: var(--r-md);
  background: var(--surface-0);
  box-shadow: var(--shadow-md);
  font-size: var(--text-sm);
  pointer-events: none;
}

.tooltip strong {
  display: block;
  margin-bottom: 3px;
  font-weight: 600;
  color: var(--ink-900);
}

.tip-row {
  display: flex;
  align-items: center;
  gap: 6px;
  color: var(--ink-500);
}

.tip-name {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.tip-value {
  color: var(--ink-900);
  font-variant-numeric: tabular-nums;
}

.data {
  max-height: 320px;
  overflow: auto;
}

.note {
  margin-top: 6px;
  font-size: var(--text-sm);
  color: var(--ink-400);
}
</style>
