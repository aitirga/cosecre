<script setup lang="ts">
/**
 * Draws an `AimPlotSpec` as inline SVG.
 *
 * Nothing the model wrote reaches the DOM as markup — the spec is data, and
 * every element here is authored locally. The only model-written "code" is a
 * function expression, which `expression.ts` parses rather than evaluates.
 *
 * Colours come from the design tokens, so a figure looks like the rest of the
 * app instead of like a charting library.
 */
import { computed } from 'vue'

import { compileExpression } from './expression'
import type {
  AimBarsPlot,
  AimFunctionPlot,
  AimGeometryPlot,
  AimPlotSpec,
  AimPointsPlot,
} from '../types'

const props = withDefaults(defineProps<{ spec: AimPlotSpec; height?: number }>(), { height: 220 })

const WIDTH = 420
const PAD = { top: 22, right: 14, bottom: 34, left: 40 }
const SAMPLES = 240

/** Four hues that stay distinguishable on the paper surfaces. */
const SERIES_COLORS = [
  'var(--accent-700)',
  'var(--olive-700)',
  'var(--gold-800)',
  'var(--ink-500)',
]

interface Frame {
  xMin: number
  xMax: number
  yMin: number
  yMax: number
}

interface Line {
  label: string
  color: string
  d: string
  dots: { x: number; y: number }[]
}

const plotHeight = computed(() => props.height)
const innerWidth = WIDTH - PAD.left - PAD.right
const innerHeight = computed(() => plotHeight.value - PAD.top - PAD.bottom)

/** Anything non-finite is a hole in the curve, not a point at zero. */
function finite(value: number): number | null {
  return Number.isFinite(value) ? value : null
}

/** Collect every (x, y) the spec implies, before deciding on a frame. */
const sampled = computed<{ label: string; points: (readonly [number, number] | null)[] }[]>(() => {
  const spec = props.spec
  if (spec.kind === 'function') {
    const span = spec.x_max - spec.x_min || 1
    return spec.series.map((series) => {
      const evaluate = compileExpression(series.expression)
      const points = Array.from({ length: SAMPLES + 1 }, (_, index) => {
        const x = spec.x_min + (span * index) / SAMPLES
        const y = finite(evaluate(x))
        return y === null ? null : ([x, y] as const)
      })
      return { label: series.label, points }
    })
  }
  if (spec.kind === 'points') {
    return spec.series.map((series) => ({
      label: series.label,
      points: series.points.map((point) => [point[0], point[1]] as const),
    }))
  }
  return []
})

const frame = computed<Frame>(() => {
  const spec = props.spec
  const xs: number[] = []
  const ys: number[] = []

  for (const series of sampled.value) {
    for (const point of series.points) {
      if (!point) continue
      xs.push(point[0])
      ys.push(point[1])
    }
  }
  if (spec.kind === 'geometry') {
    for (const shape of spec.shapes) {
      if (shape.type === 'circle') {
        const [cx, cy, r] = shape.coords
        xs.push(cx - r, cx + r)
        ys.push(cy - r, cy + r)
        continue
      }
      shape.coords.forEach((value, index) => (index % 2 === 0 ? xs.push(value) : ys.push(value)))
    }
  }
  if (spec.kind === 'function') {
    xs.push(spec.x_min, spec.x_max)
    for (const marker of spec.markers ?? []) {
      xs.push(marker.x)
      ys.push(marker.y)
    }
  }

  if (!xs.length || !ys.length) return { xMin: 0, xMax: 1, yMin: 0, yMax: 1 }

  let [xMin, xMax] = [Math.min(...xs), Math.max(...xs)]
  let [yMin, yMax] = [Math.min(...ys), Math.max(...ys)]

  // A function with a pole would otherwise flatten everything else to a line.
  if (props.spec.kind === 'function' && yMax - yMin > 1e4) {
    yMin = Math.max(yMin, -100)
    yMax = Math.min(yMax, 100)
  }
  if (xMax - xMin < 1e-9) [xMin, xMax] = [xMin - 1, xMax + 1]
  if (yMax - yMin < 1e-9) [yMin, yMax] = [yMin - 1, yMax + 1]

  const margin = (yMax - yMin) * 0.08
  return { xMin, xMax, yMin: yMin - margin, yMax: yMax + margin }
})

function toX(value: number): number {
  const { xMin, xMax } = frame.value
  return PAD.left + ((value - xMin) / (xMax - xMin)) * innerWidth
}

function toY(value: number): number {
  const { yMin, yMax } = frame.value
  return PAD.top + innerHeight.value - ((value - yMin) / (yMax - yMin)) * innerHeight.value
}

/** Break the path wherever the function is undefined, rather than bridging it. */
const lines = computed<Line[]>(() =>
  sampled.value.map((series, index) => {
    const isScatter =
      props.spec.kind === 'points' && props.spec.series[index]?.mode === 'scatter'
    const dots: { x: number; y: number }[] = []
    let d = ''
    let penDown = false

    for (const point of series.points) {
      if (!point) {
        penDown = false
        continue
      }
      const [x, y] = [toX(point[0]), toY(point[1])]
      if (isScatter) {
        dots.push({ x, y })
        continue
      }
      d += `${penDown ? 'L' : 'M'}${x.toFixed(2)} ${y.toFixed(2)} `
      penDown = true
    }

    return {
      label: series.label,
      color: SERIES_COLORS[index % SERIES_COLORS.length],
      d: d.trim(),
      dots,
    }
  }),
)

/** Round tick values so the axis reads 0, 0.5, 1 rather than 0.4999999. */
function ticks(min: number, max: number, count = 4): number[] {
  const step = (max - min) / count
  return Array.from({ length: count + 1 }, (_, index) => {
    const value = min + step * index
    return Number(value.toFixed(Math.max(0, 2 - Math.floor(Math.log10(Math.abs(step) || 1)))))
  })
}

const xTicks = computed(() => ticks(frame.value.xMin, frame.value.xMax))
const yTicks = computed(() => ticks(frame.value.yMin, frame.value.yMax))

const asFunction = computed(() =>
  props.spec.kind === 'function' ? (props.spec as AimFunctionPlot) : null,
)
const asPoints = computed(() =>
  props.spec.kind === 'points' ? (props.spec as AimPointsPlot) : null,
)
const asBars = computed(() => (props.spec.kind === 'bars' ? (props.spec as AimBarsPlot) : null))
const asGeometry = computed(() =>
  props.spec.kind === 'geometry' ? (props.spec as AimGeometryPlot) : null,
)

const showsGrid = computed(() => props.spec.kind !== 'geometry' && (asFunction.value?.grid ?? true))
// Narrowed on `kind` rather than on the derived ref: geometry is the one kind
// with no axes, and TypeScript only follows the discriminant.
const xLabel = computed(() => (props.spec.kind === 'geometry' ? '' : props.spec.x_label))
const yLabel = computed(() => (props.spec.kind === 'geometry' ? '' : props.spec.y_label))
const legend = computed(() => lines.value.filter((line) => line.label))

/** Bars get their own band scale rather than the numeric frame. */
const bars = computed(() => {
  const spec = asBars.value
  if (!spec) return null
  const values = spec.series.flatMap((series) => series.values)
  const max = Math.max(0, ...values)
  const min = Math.min(0, ...values)
  const span = max - min || 1
  const bandWidth = innerWidth / Math.max(1, spec.categories.length)
  const barWidth = (bandWidth * 0.68) / Math.max(1, spec.series.length)
  const zeroY = PAD.top + innerHeight.value - ((0 - min) / span) * innerHeight.value

  return {
    zeroY,
    bandWidth,
    rects: spec.series.flatMap((series, seriesIndex) =>
      series.values.map((value, categoryIndex) => {
        const y = PAD.top + innerHeight.value - ((value - min) / span) * innerHeight.value
        return {
          key: `${seriesIndex}-${categoryIndex}`,
          x:
            PAD.left +
            bandWidth * categoryIndex +
            bandWidth * 0.16 +
            barWidth * seriesIndex,
          y: Math.min(y, zeroY),
          width: Math.max(1, barWidth - 2),
          height: Math.max(1, Math.abs(zeroY - y)),
          color: SERIES_COLORS[seriesIndex % SERIES_COLORS.length],
        }
      }),
    ),
    labels: spec.categories.map((label, index) => ({
      label,
      x: PAD.left + bandWidth * (index + 0.5),
    })),
    legend: spec.series.map((series, index) => ({
      label: series.label,
      color: SERIES_COLORS[index % SERIES_COLORS.length],
    })),
  }
})

const geometry = computed(() => {
  const spec = asGeometry.value
  if (!spec) return null
  return spec.shapes.map((shape, index) => {
    const color = SERIES_COLORS[index % SERIES_COLORS.length]
    if (shape.type === 'circle') {
      const [cx, cy, r] = shape.coords
      return {
        kind: 'circle' as const,
        color,
        label: shape.label,
        cx: toX(cx),
        cy: toY(cy),
        // Radius is scaled on x; the frame keeps both axes to the same extent.
        r: Math.abs(toX(cx + r) - toX(cx)),
      }
    }
    const points: string[] = []
    for (let i = 0; i + 1 < shape.coords.length; i += 2) {
      points.push(`${toX(shape.coords[i]).toFixed(2)},${toY(shape.coords[i + 1]).toFixed(2)}`)
    }
    if (shape.type === 'label') {
      return {
        kind: 'label' as const,
        color,
        label: shape.label,
        x: toX(shape.coords[0] ?? 0),
        y: toY(shape.coords[1] ?? 0),
      }
    }
    return {
      kind: shape.type === 'polygon' ? ('polygon' as const) : ('segment' as const),
      color,
      label: shape.label,
      points: points.join(' '),
    }
  })
})
</script>

<template>
  <figure class="plot">
    <svg
      :viewBox="`0 0 ${WIDTH} ${plotHeight}`"
      :aria-label="spec.title"
      role="img"
      preserveAspectRatio="xMidYMid meet"
    >
      <title>{{ spec.title }}</title>

      <g v-if="showsGrid" class="grid">
        <line
          v-for="tick in xTicks"
          :key="`gx-${tick}`"
          :x1="toX(tick)"
          :x2="toX(tick)"
          :y1="PAD.top"
          :y2="PAD.top + innerHeight"
        />
        <line
          v-for="tick in yTicks"
          :key="`gy-${tick}`"
          :x1="PAD.left"
          :x2="PAD.left + innerWidth"
          :y1="toY(tick)"
          :y2="toY(tick)"
        />
      </g>

      <g class="axis">
        <line
          :x1="PAD.left"
          :x2="PAD.left + innerWidth"
          :y1="PAD.top + innerHeight"
          :y2="PAD.top + innerHeight"
        />
        <line :x1="PAD.left" :x2="PAD.left" :y1="PAD.top" :y2="PAD.top + innerHeight" />
      </g>

      <g v-if="!asBars" class="ticks">
        <text
          v-for="tick in xTicks"
          :key="`tx-${tick}`"
          :x="toX(tick)"
          :y="PAD.top + innerHeight + 13"
          text-anchor="middle"
        >
          {{ tick }}
        </text>
        <text
          v-for="tick in yTicks"
          :key="`ty-${tick}`"
          :x="PAD.left - 6"
          :y="toY(tick) + 3"
          text-anchor="end"
        >
          {{ tick }}
        </text>
      </g>

      <!-- Curves and scatter -->
      <g v-if="asFunction || asPoints">
        <template v-for="(line, index) in lines" :key="`s-${index}`">
          <path v-if="line.d" :d="line.d" fill="none" :stroke="line.color" stroke-width="1.75" />
          <circle
            v-for="(dot, dotIndex) in line.dots"
            :key="`d-${index}-${dotIndex}`"
            :cx="dot.x"
            :cy="dot.y"
            r="2.5"
            :fill="line.color"
          />
        </template>
        <g v-if="asFunction?.markers" class="markers">
          <template v-for="(marker, index) in asFunction.markers" :key="`m-${index}`">
            <circle :cx="toX(marker.x)" :cy="toY(marker.y)" r="3.5" />
            <text :x="toX(marker.x) + 6" :y="toY(marker.y) - 5">{{ marker.label }}</text>
          </template>
        </g>
      </g>

      <!-- Bars -->
      <g v-else-if="bars">
        <rect
          v-for="rect in bars.rects"
          :key="rect.key"
          :x="rect.x"
          :y="rect.y"
          :width="rect.width"
          :height="rect.height"
          :fill="rect.color"
          rx="2"
        />
        <g class="ticks">
          <text
            v-for="label in bars.labels"
            :key="label.label"
            :x="label.x"
            :y="PAD.top + innerHeight + 13"
            text-anchor="middle"
          >
            {{ label.label }}
          </text>
        </g>
      </g>

      <!-- Geometry -->
      <g v-else-if="geometry" class="geometry">
        <template v-for="(shape, index) in geometry" :key="`g-${index}`">
          <circle
            v-if="shape.kind === 'circle'"
            :cx="shape.cx"
            :cy="shape.cy"
            :r="shape.r"
            fill="none"
            :stroke="shape.color"
            stroke-width="1.75"
          />
          <polygon
            v-else-if="shape.kind === 'polygon'"
            :points="shape.points"
            fill="none"
            :stroke="shape.color"
            stroke-width="1.75"
          />
          <polyline
            v-else-if="shape.kind === 'segment'"
            :points="shape.points"
            fill="none"
            :stroke="shape.color"
            stroke-width="1.75"
          />
          <text v-else :x="shape.x" :y="shape.y" :fill="shape.color">{{ shape.label }}</text>
        </template>
      </g>

      <text
        v-if="xLabel"
        class="axis-label"
        :x="PAD.left + innerWidth / 2"
        :y="plotHeight - 4"
        text-anchor="middle"
      >
        {{ xLabel }}
      </text>
      <text v-if="yLabel" class="axis-label" x="10" :y="PAD.top + innerHeight / 2" text-anchor="middle"
        :transform="`rotate(-90 10 ${PAD.top + innerHeight / 2})`">
        {{ yLabel }}
      </text>
    </svg>

    <figcaption>
      <span class="plot-title">{{ spec.title }}</span>
      <span v-if="bars?.legend.length || legend.length" class="legend">
        <span v-for="item in bars?.legend ?? legend" :key="item.label" class="legend-item">
          <span class="swatch" :style="{ background: item.color }" />
          {{ item.label }}
        </span>
      </span>
    </figcaption>
  </figure>
</template>

<style scoped>
.plot {
  margin: 0;
  display: grid;
  gap: 6px;
}

svg {
  width: 100%;
  height: auto;
  background: var(--surface-0);
  border: 1px solid var(--line);
  border-radius: var(--r-md);
}

.grid line {
  stroke: var(--line);
  stroke-width: 1;
}

.axis line {
  stroke: var(--line-strong);
  stroke-width: 1;
}

.ticks text,
.axis-label {
  font-size: 9px;
  fill: var(--ink-400);
}

.axis-label {
  font-size: 10px;
}

.markers circle {
  fill: var(--accent-500);
}

.markers text,
.geometry text {
  font-size: 9px;
  fill: var(--ink-700);
}

figcaption {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  flex-wrap: wrap;
  font-size: var(--text-sm);
}

.plot-title {
  color: var(--ink-700);
  font-weight: 500;
}

.legend {
  display: flex;
  gap: 10px;
  flex-wrap: wrap;
  color: var(--ink-400);
  font-size: var(--text-xs);
}

.legend-item {
  display: inline-flex;
  align-items: center;
  gap: 4px;
}

.swatch {
  width: 8px;
  height: 8px;
  border-radius: var(--r-xs);
}
</style>
