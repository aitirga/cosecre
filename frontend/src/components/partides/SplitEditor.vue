<script setup lang="ts">
import { computed, ref, watch } from 'vue'

import { formatAmount, parseAmount } from '../../document-fields'
import AppIcon from '../AppIcon.vue'

/**
 * How an invoice is shared between its budget lines.
 *
 * One bar, one segment per line, in each line's fund colour: drag the seam
 * between two segments and only those two change, so the total always holds.
 * The rows below say the same in numbers, typed in euros or in percent — the
 * hub only ever stores euros. When the invoice has no amount there is nothing
 * to be a percentage of, so the bar shows the amounts' own proportions and the
 * percent mode is off.
 */
export interface SplitLine {
  id: number
  title: string
  code: string
  colour: string
}

const props = defineProps<{
  lines: SplitLine[]
  /** The invoice's amount, or null when the register does not know it. */
  total: number | null
  /** Euros per line id. */
  modelValue: Record<number, number | null>
}>()
const emit = defineEmits<{ 'update:modelValue': [value: Record<number, number | null>] }>()

const mode = ref<'eur' | 'pct'>('eur')
const bar = ref<HTMLElement | null>(null)

const cents = (value: number) => Math.round(value * 100) / 100
const amountOf = (id: number) => props.modelValue[id] ?? 0
const sum = computed(() => cents(props.lines.reduce((acc, line) => acc + amountOf(line.id), 0)))
const base = computed(() => (props.total && props.total > 0 ? props.total : sum.value))
const gap = computed(() => (props.total === null ? 0 : cents(props.total - sum.value)))
const balanced = computed(() => props.total === null || Math.abs(gap.value) < 0.005)

watch(
  () => props.total,
  (total) => {
    if (total === null || total <= 0) mode.value = 'eur'
  },
  { immediate: true },
)

function percentOf(id: number) {
  return base.value > 0 ? (amountOf(id) / base.value) * 100 : 0
}

function set(next: Record<number, number | null>) {
  emit('update:modelValue', { ...props.modelValue, ...next })
}

function even() {
  const total = props.total ?? sum.value
  const n = props.lines.length
  if (!n || total <= 0) return
  const share = Math.floor((total * 100) / n) / 100
  const next: Record<number, number> = {}
  props.lines.forEach((line, index) => {
    next[line.id] = index === n - 1 ? cents(total - share * (n - 1)) : share
  })
  set(next)
}

/** This line takes whatever the others leave. */
function rest(id: number) {
  if (props.total === null) return
  const others = props.lines.reduce((acc, line) => (line.id === id ? acc : acc + amountOf(line.id)), 0)
  set({ [id]: Math.max(0, cents(props.total - others)) })
}

// ── Typing ──────────────────────────────────────────────────────────────────
// What is typed stays as typed until the field is left, then is read and
// written back in the canonical form.

const drafts = ref<Record<number, string>>({})

function shown(id: number) {
  if (id in drafts.value) return drafts.value[id]
  if (props.modelValue[id] == null) return ''
  return mode.value === 'eur'
    ? amountOf(id).toLocaleString('ca-ES', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
    : percentOf(id).toLocaleString('ca-ES', { maximumFractionDigits: 2 })
}

function commit(id: number) {
  const text = drafts.value[id]
  delete drafts.value[id]
  if (text === undefined) return
  const value = parseAmount(text.replace('%', ''))
  if (value === undefined) return
  if (value === null) return set({ [id]: null })
  set({ [id]: cents(mode.value === 'eur' ? value : ((props.total ?? 0) * value) / 100) })
}

// ── Dragging a seam ─────────────────────────────────────────────────────────

let drag: { index: number; pair: number; startX: number; startLeft: number; width: number } | null = null

function startSeam(event: PointerEvent, index: number) {
  if (!bar.value || event.button !== 0) return
  const left = props.lines[index]
  const right = props.lines[index + 1]
  ;(event.currentTarget as HTMLElement).setPointerCapture(event.pointerId)
  drag = {
    index,
    pair: amountOf(left.id) + amountOf(right.id),
    startX: event.clientX,
    startLeft: amountOf(left.id),
    width: bar.value.getBoundingClientRect().width,
  }
  event.preventDefault()
}

function moveSeam(event: PointerEvent) {
  if (!drag || base.value <= 0) return
  const delta = ((event.clientX - drag.startX) / drag.width) * base.value
  // Whole percents snap unless Alt is held, which goes to the cent.
  const step = event.altKey ? 0.01 : Math.max(0.01, base.value / 100)
  const raw = Math.round((drag.startLeft + delta) / step) * step
  const left = cents(Math.min(Math.max(raw, 0), drag.pair))
  set({
    [props.lines[drag.index].id]: left,
    [props.lines[drag.index + 1].id]: cents(drag.pair - left),
  })
}

function endSeam() {
  drag = null
}

/** Arrow keys on a seam move it by a percent (Shift: ten). */
function keySeam(event: KeyboardEvent, index: number) {
  const direction = event.key === 'ArrowLeft' ? -1 : event.key === 'ArrowRight' ? 1 : 0
  if (!direction || base.value <= 0) return
  event.preventDefault()
  const left = props.lines[index]
  const right = props.lines[index + 1]
  const pair = amountOf(left.id) + amountOf(right.id)
  const step = (base.value / 100) * (event.shiftKey ? 10 : 1)
  const next = cents(Math.min(Math.max(amountOf(left.id) + direction * step, 0), pair))
  set({ [left.id]: next, [right.id]: cents(pair - next) })
}

/** Where each seam sits, as a percentage of the bar. */
const seams = computed(() => {
  let running = 0
  return props.lines.slice(0, -1).map((line) => {
    running += percentOf(line.id)
    return Math.min(100, running)
  })
})

defineExpose({ balanced, even })
</script>

<template>
  <section class="split" aria-label="Repartiment entre partides">
    <header class="split-head">
      <span class="split-title">
        <AppIcon name="layers" :size="13" />
        Repartiment
      </span>
      <div class="split-tools">
        <div class="seg" role="radiogroup" aria-label="Unitat">
          <button
            type="button"
            role="radio"
            :aria-checked="mode === 'eur'"
            :class="{ on: mode === 'eur' }"
            @click="mode = 'eur'"
          >
            €
          </button>
          <button
            type="button"
            role="radio"
            :aria-checked="mode === 'pct'"
            :class="{ on: mode === 'pct' }"
            :disabled="!total"
            :title="total ? '' : 'La factura no té import'"
            @click="mode = 'pct'"
          >
            %
          </button>
        </div>
        <button type="button" class="btn btn-ghost btn-sm" @click="even">A parts iguals</button>
      </div>
    </header>

    <div
      ref="bar"
      class="bar"
      :class="{ 'is-off': !balanced }"
      @pointermove="moveSeam"
      @pointerup="endSeam"
      @pointercancel="endSeam"
    >
      <span
        v-for="line in lines"
        :key="line.id"
        class="bar-seg"
        :style="{ width: `${percentOf(line.id)}%`, background: line.colour }"
        :title="`${line.title} · ${formatAmount(amountOf(line.id))}`"
      >
        <span v-if="percentOf(line.id) >= 9" class="bar-label">{{ Math.round(percentOf(line.id)) }} %</span>
      </span>
      <span v-if="total && gap > 0" class="bar-gap" :style="{ width: `${(gap / total) * 100}%` }" />
      <button
        v-for="(at, index) in seams"
        :key="`seam-${index}`"
        type="button"
        class="seam"
        :style="{ left: `${at}%` }"
        :aria-label="`Mou el límit entre ${lines[index].title} i ${lines[index + 1].title}`"
        @pointerdown="startSeam($event, index)"
        @keydown="keySeam($event, index)"
      />
    </div>

    <ul class="rows">
      <li v-for="line in lines" :key="line.id" class="row">
        <span class="dot" :style="{ background: line.colour }" />
        <span class="row-name">
          {{ line.title }}
          <span class="mono subtle">{{ line.code }}</span>
        </span>
        <span class="row-controls">
        <label class="amount">
          <input
            class="input input-mono"
            inputmode="decimal"
            :value="shown(line.id)"
            :aria-label="`${mode === 'eur' ? 'Import' : 'Percentatge'} de ${line.title}`"
            @input="drafts[line.id] = ($event.target as HTMLInputElement).value"
            @blur="commit(line.id)"
            @keydown.enter.prevent="commit(line.id)"
          />
          <span class="unit">{{ mode === 'eur' ? '€' : '%' }}</span>
        </label>
        <span class="other mono">
          {{
            mode === 'eur'
              ? `${percentOf(line.id).toLocaleString('ca-ES', { maximumFractionDigits: 1 })} %`
              : formatAmount(amountOf(line.id))
          }}
        </span>
        <button
          type="button"
          class="btn btn-ghost btn-sm rest"
          :disabled="total === null || (balanced && amountOf(line.id) > 0)"
          title="Aquesta partida es queda la resta"
          @click="rest(line.id)"
        >
          la resta
        </button>
        </span>
      </li>
    </ul>

    <footer class="split-foot" :class="balanced ? 'is-ok' : gap > 0 ? 'is-short' : 'is-over'">
      <template v-if="total === null">
        <AppIcon name="info" :size="13" />
        La factura no té import: es desa el que escriguis ({{ formatAmount(sum) }}).
      </template>
      <template v-else-if="balanced">
        <AppIcon name="check" :size="13" />
        Quadra amb la factura · {{ formatAmount(total) }}
      </template>
      <template v-else-if="gap > 0">
        <AppIcon name="alert" :size="13" />
        Falten {{ formatAmount(gap) }} per arribar a {{ formatAmount(total) }}
      </template>
      <template v-else>
        <AppIcon name="alert" :size="13" />
        Sobren {{ formatAmount(-gap) }} sobre {{ formatAmount(total) }}
      </template>
    </footer>
  </section>
</template>

<style scoped>
.split {
  display: grid;
  gap: 10px;
  padding: 12px;
  border: 1px solid var(--line);
  border-radius: var(--r-lg);
  background: var(--surface-0);
}

.split-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}

.split-title {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  color: var(--ink-700);
  font-size: var(--text-sm);
  font-weight: 600;
}

.split-tools {
  display: flex;
  align-items: center;
  gap: 6px;
}

.seg {
  display: inline-flex;
  padding: 2px;
  border: 1px solid var(--line-strong);
  border-radius: var(--r-md);
  background: var(--surface-1);
}

.seg button {
  min-width: 28px;
  padding: 2px 8px;
  border: 0;
  border-radius: var(--r-sm);
  background: none;
  color: var(--ink-500);
  font: inherit;
  font-size: var(--text-sm);
  font-weight: 600;
  cursor: pointer;
}

.seg button.on {
  background: var(--surface-0);
  color: var(--ink-900);
  box-shadow: var(--shadow-xs);
}

.seg button:disabled {
  opacity: 0.4;
  cursor: not-allowed;
}

/* ── The bar ──────────────────────────────────────────────────────────── */
.bar {
  position: relative;
  display: flex;
  height: 26px;
  overflow: visible;
  border-radius: var(--r-md);
  background: var(--surface-3);
  touch-action: none;
}

.bar-seg {
  display: grid;
  place-items: center;
  min-width: 0;
  height: 100%;
  overflow: hidden;
  transition: width 0.08s linear;
}

.bar-seg:first-child {
  border-radius: var(--r-md) 0 0 var(--r-md);
}

.bar-seg:last-of-type {
  border-radius: 0 var(--r-md) var(--r-md) 0;
}

.bar-label {
  color: #fff;
  font-size: var(--text-xs);
  font-weight: 600;
  font-variant-numeric: tabular-nums;
  text-shadow: 0 1px 1px rgba(0, 0, 0, 0.25);
}

/* What is still unassigned: hatched, so it reads as a hole, not a line. */
.bar-gap {
  height: 100%;
  background: repeating-linear-gradient(
    -45deg,
    var(--gold-100),
    var(--gold-100) 4px,
    var(--gold-200) 4px,
    var(--gold-200) 8px
  );
  border-radius: 0 var(--r-md) var(--r-md) 0;
}

.bar.is-off {
  outline: 1px solid var(--gold-200);
  outline-offset: 2px;
}

.seam {
  position: absolute;
  top: -3px;
  bottom: -3px;
  width: 12px;
  margin-left: -6px;
  padding: 0;
  border: 0;
  background: none;
  cursor: ew-resize;
}

.seam::before {
  content: '';
  position: absolute;
  top: 0;
  bottom: 0;
  left: 4px;
  width: 4px;
  border-radius: 2px;
  background: var(--surface-0);
  box-shadow: 0 0 0 1px var(--line-strong), var(--shadow-sm);
}

.seam:hover::before,
.seam:focus-visible::before {
  box-shadow: 0 0 0 2px var(--accent-500), var(--shadow-sm);
}

.seam:focus-visible {
  outline: none;
}

/* ── Rows ─────────────────────────────────────────────────────────────── */
.rows {
  display: grid;
  margin: 0;
  padding: 0;
  list-style: none;
}

/* Name on its own line, the numbers under it: a budget line's name is long
   and is what tells two rows apart. */
.row {
  display: grid;
  grid-template-columns: 8px minmax(0, 1fr);
  align-items: center;
  gap: 4px 8px;
  padding: 6px 0;
}

.row + .row {
  border-top: 1px solid var(--line);
}

.dot {
  width: 8px;
  height: 8px;
  border-radius: 2px;
}

.row-name {
  min-width: 0;
  font-size: var(--text-sm);
  font-weight: 500;
  line-height: 1.3;
}

.row-name .subtle {
  margin-left: 4px;
  font-size: var(--text-xs);
  font-weight: 400;
}

.row-controls {
  display: flex;
  grid-column: 2;
  align-items: center;
  gap: 8px;
}

.amount {
  flex: 0 1 132px;
}

.amount {
  position: relative;
}

.amount .input {
  height: 28px;
  padding-right: 22px;
  text-align: right;
}

.unit {
  position: absolute;
  top: 50%;
  right: 8px;
  color: var(--ink-400);
  font-size: var(--text-sm);
  transform: translateY(-50%);
  pointer-events: none;
}

.other {
  min-width: 56px;
  color: var(--ink-400);
  font-size: var(--text-sm);
  text-align: right;
}

.rest {
  margin-left: auto;
  padding-inline: 6px;
  font-size: var(--text-xs);
}

.split-foot {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 6px 8px;
  border-radius: var(--r-md);
  font-size: var(--text-sm);
  font-weight: 500;
}

.split-foot.is-ok {
  background: var(--olive-100);
  color: var(--olive-700);
}

.split-foot.is-short,
.split-foot.is-over {
  background: var(--gold-100);
  color: var(--gold-800);
}

@media (prefers-reduced-motion: reduce) {
  .bar-seg {
    transition: none;
  }
}
</style>
