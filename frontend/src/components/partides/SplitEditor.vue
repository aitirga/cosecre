<script setup lang="ts">
import { computed, ref } from 'vue'

import { formatAmount, parseAmount } from '../../document-fields'
import { type Share, evenShares, rebalance } from '../../partides'
import AppIcon from '../AppIcon.vue'

/**
 * What a movement is charged to: one line, or how it is shared between several.
 *
 * One bar, one segment per line in its fund's colour, labelled. Drag the seam
 * between two segments and only those two change. Each row takes euros or a
 * percent, as typed, and the other lines make room in the proportions they
 * had — so the split always adds up to the movement and there is nothing to
 * pin or balance by hand. The hub only ever stores euros.
 */
export interface SplitLine {
  id: number
  title: string
  code: string
  fund: string
  colour: string
  soft: string
  /** Only Jev's proposal so far: drawn in violet until it is saved. */
  jev?: boolean
}

const props = defineProps<{
  lines: SplitLine[]
  /** The movement's amount (unsigned), or null when it is not known. */
  total: number | null
  modelValue: Share[]
}>()
const emit = defineEmits<{ 'update:modelValue': [value: Share[]]; remove: [id: number] }>()

const bar = ref<HTMLElement | null>(null)
/** The line under the pointer, in the bar or the rows: lit in both. */
const hot = ref<number | null>(null)

const cents = (value: number) => Math.round(value * 100) / 100
const single = computed(() => props.lines.length === 1)
const amountOf = (id: number) =>
  single.value ? (props.total ?? 0) : (props.modelValue.find((share) => share.id === id)?.amount ?? 0)
const sum = computed(() => cents(props.lines.reduce((acc, line) => acc + amountOf(line.id), 0)))
const base = computed(() => (props.total && props.total > 0 ? props.total : sum.value))
const gap = computed(() => (props.total === null || single.value ? 0 : cents(props.total - sum.value)))
const balanced = computed(() => props.total === null || Math.abs(gap.value) < 0.005)

function percentOf(id: number) {
  if (single.value) return 100
  return base.value > 0 ? (amountOf(id) / base.value) * 100 : 0
}

function setAmount(id: number, value: number) {
  emit('update:modelValue', rebalance(props.modelValue, id, value, props.total))
}

function even() {
  emit('update:modelValue', evenShares(props.lines.map((line) => line.id), props.total))
}

// ── Typing ──────────────────────────────────────────────────────────────────
// The field being typed in keeps its text; every other number follows live.

const editing = ref<{ id: number; unit: 'eur' | 'pct'; text: string } | null>(null)

function shown(id: number, unit: 'eur' | 'pct') {
  if (editing.value?.id === id && editing.value.unit === unit) return editing.value.text
  return unit === 'eur'
    ? amountOf(id).toLocaleString('ca-ES', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
    : percentOf(id).toLocaleString('ca-ES', { maximumFractionDigits: 1 })
}

function onType(id: number, unit: 'eur' | 'pct', text: string) {
  editing.value = { id, unit, text }
  const value = parseAmount(text.replace('%', ''))
  if (value === undefined || value === null) return
  if (unit === 'pct' && !props.total) return
  setAmount(id, unit === 'eur' ? value : ((props.total ?? 0) * value) / 100)
}

function leave() {
  editing.value = null
}

// ── Dragging a seam ─────────────────────────────────────────────────────────

let drag: { index: number; pair: number; startX: number; startLeft: number; width: number } | null = null

function pairSet(index: number, left: number, pair: number) {
  const a = props.lines[index].id
  const b = props.lines[index + 1].id
  emit(
    'update:modelValue',
    props.modelValue.map((share) =>
      share.id === a ? { ...share, amount: left } : share.id === b ? { ...share, amount: cents(pair - left) } : share,
    ),
  )
}

function startSeam(event: PointerEvent, index: number) {
  if (!bar.value || event.button !== 0) return
  ;(event.currentTarget as HTMLElement).setPointerCapture(event.pointerId)
  const left = amountOf(props.lines[index].id)
  drag = {
    index,
    pair: left + amountOf(props.lines[index + 1].id),
    startX: event.clientX,
    startLeft: left,
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
  pairSet(drag.index, cents(Math.min(Math.max(raw, 0), drag.pair)), drag.pair)
}

function endSeam() {
  drag = null
}

/** Arrow keys on a seam move it by a percent (Shift: ten). */
function keySeam(event: KeyboardEvent, index: number) {
  const direction = event.key === 'ArrowLeft' ? -1 : event.key === 'ArrowRight' ? 1 : 0
  if (!direction || base.value <= 0) return
  event.preventDefault()
  const left = amountOf(props.lines[index].id)
  const pair = left + amountOf(props.lines[index + 1].id)
  const step = (base.value / 100) * (event.shiftKey ? 10 : 1)
  pairSet(index, cents(Math.min(Math.max(left + direction * step, 0), pair)), pair)
}

/** Where each seam sits, as a percentage of the bar. */
const seams = computed(() => {
  let running = 0
  return props.lines.slice(0, -1).map((line) => {
    running += percentOf(line.id)
    return Math.min(100, running)
  })
})

function pctLabel(id: number) {
  return `${percentOf(id).toLocaleString('ca-ES', { maximumFractionDigits: 0 })} %`
}

defineExpose({ balanced, even })
</script>

<template>
  <section class="split" :class="{ 'is-single': single }" aria-label="Repartiment entre partides">
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
        :class="{ 'is-hot': hot === line.id, 'is-jev': line.jev }"
        :style="{ width: `${percentOf(line.id)}%`, '--tone': line.colour }"
        :title="`${line.title} · ${formatAmount(amountOf(line.id))} · ${pctLabel(line.id)}`"
        @pointerenter="hot = line.id"
        @pointerleave="hot = null"
      >
        <span v-if="percentOf(line.id) >= 22" class="bar-name">{{ line.title }}</span>
        <span v-if="percentOf(line.id) >= 8" class="bar-pct">{{ pctLabel(line.id) }}</span>
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

    <ul v-if="!single" class="rows">
      <li
        v-for="line in lines"
        :key="line.id"
        class="row"
        :class="{ 'is-hot': hot === line.id, 'is-jev': line.jev }"
        :style="{ '--tone': line.colour, '--tone-soft': line.soft }"
        @pointerenter="hot = line.id"
        @pointerleave="hot = null"
      >
        <span class="row-name">
          <span class="row-title" :title="line.title">
            <AppIcon v-if="line.jev" name="sparkles" :size="11" class="ai-mark" />
            {{ line.title }}
          </span>
          <span class="row-sub mono">{{ line.code }}<template v-if="line.fund"> · {{ line.fund }}</template></span>
        </span>
        <template v-if="single">
          <span class="row-whole mono">{{ formatAmount(total) }}</span>
        </template>
        <template v-else>
          <label class="field field-eur">
            <input
              class="input input-mono"
              inputmode="decimal"
              :value="shown(line.id, 'eur')"
              :aria-label="`Import de ${line.title}`"
              @input="onType(line.id, 'eur', ($event.target as HTMLInputElement).value)"
              @focus="($event.target as HTMLInputElement).select()"
              @blur="leave"
              @keydown.enter.prevent="($event.target as HTMLInputElement).blur()"
            />
            <span class="unit">€</span>
          </label>
          <label class="field field-pct">
            <input
              class="input input-mono"
              inputmode="decimal"
              :value="shown(line.id, 'pct')"
              :disabled="!total"
              :aria-label="`Percentatge de ${line.title}`"
              @input="onType(line.id, 'pct', ($event.target as HTMLInputElement).value)"
              @focus="($event.target as HTMLInputElement).select()"
              @blur="leave"
              @keydown.enter.prevent="($event.target as HTMLInputElement).blur()"
            />
            <span class="unit">%</span>
          </label>
        </template>
        <button type="button" class="btn btn-ghost btn-icon btn-sm" :title="`Treu ${line.title}`" @click="emit('remove', line.id)">
          <AppIcon name="close" :size="12" />
        </button>
      </li>
    </ul>

    <footer v-if="!single" class="split-foot" :class="balanced ? 'is-ok' : gap > 0 ? 'is-short' : 'is-over'">
      <span class="foot-text">
        <template v-if="total === null">
          <AppIcon name="info" :size="13" />
          Sense import: es desa el que escriguis ({{ formatAmount(sum) }}).
        </template>
        <template v-else-if="balanced">
          <AppIcon name="check" :size="13" />
          Quadra amb el moviment · {{ formatAmount(total) }}
        </template>
        <template v-else-if="gap > 0">
          <AppIcon name="alert" :size="13" />
          Falten {{ formatAmount(gap) }} per arribar a {{ formatAmount(total) }}
        </template>
        <template v-else>
          <AppIcon name="alert" :size="13" />
          Sobren {{ formatAmount(-gap) }} sobre {{ formatAmount(total) }}
        </template>
      </span>
      <button type="button" class="btn btn-ghost btn-sm" @click="even">A parts iguals</button>
    </footer>
  </section>
</template>

<style scoped>
.split {
  display: grid;
  gap: 8px;
}

/* ── The bar ──────────────────────────────────────────────────────────── */
.bar {
  position: relative;
  display: flex;
  height: 28px;
  border-radius: var(--r-md);
  background: var(--surface-3);
  touch-action: none;
}

.bar-seg {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  min-width: 0;
  height: 100%;
  padding: 0 6px;
  overflow: hidden;
  background: var(--tone);
  color: #fff;
  transition:
    width 0.08s linear,
    filter 0.1s;
}

.bar-seg + .bar-seg {
  box-shadow: inset 1px 0 0 rgba(255, 255, 255, 0.55);
}

.bar-seg:first-child {
  border-radius: var(--r-md) 0 0 var(--r-md);
}

.bar-seg:last-of-type {
  border-radius: 0 var(--r-md) var(--r-md) 0;
}

.split.is-single .bar-seg {
  border-radius: var(--r-md);
}

.bar-seg.is-hot {
  filter: brightness(1.08) saturate(1.1);
}

/* Jev's, not saved: the fund's colour, striped, so it reads as a draft. */
.bar-seg.is-jev {
  background: repeating-linear-gradient(
    -45deg,
    var(--tone),
    var(--tone) 6px,
    color-mix(in srgb, var(--tone) 78%, #fff) 6px,
    color-mix(in srgb, var(--tone) 78%, #fff) 12px
  );
}

.bar-name {
  min-width: 0;
  overflow: hidden;
  font-size: var(--text-xs);
  font-weight: 500;
  text-overflow: ellipsis;
  white-space: nowrap;
  opacity: 0.92;
}

.bar-pct {
  flex: none;
  font-size: var(--text-xs);
  font-weight: 700;
  font-variant-numeric: tabular-nums;
}

.bar-name,
.bar-pct {
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
  top: -4px;
  bottom: -4px;
  width: 14px;
  margin-left: -7px;
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
  left: 5px;
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

/* ── Rows: one line each, so several lines stay short ─────────────────── */
.rows {
  display: grid;
  gap: 3px;
  margin: 0;
  padding: 0;
  list-style: none;
}

.row {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 84px 54px 22px;
  align-items: center;
  gap: 4px;
  padding: 4px 2px 4px 8px;
  border: 1px solid var(--line);
  border-left: 3px solid var(--tone);
  border-radius: var(--r-md);
  background: var(--surface-0);
}

.split.is-single .row {
  grid-template-columns: minmax(0, 1fr) auto 26px;
}

.row.is-hot {
  background: var(--tone-soft);
}

.row.is-jev {
  border-style: dashed dashed dashed solid;
  border-color: var(--ai-200);
  border-left-color: var(--tone);
  background: var(--ai-50);
}

.row-name {
  display: grid;
  min-width: 0;
  line-height: 1.25;
}

.row-title {
  overflow: hidden;
  font-size: var(--text-sm);
  font-weight: 600;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.row-sub {
  overflow: hidden;
  color: var(--ink-400);
  font-size: var(--text-xs);
  text-overflow: ellipsis;
  white-space: nowrap;
}

.row-whole {
  font-size: var(--text-base);
  font-weight: 600;
}

.field {
  position: relative;
}

.field .input {
  width: 100%;
  height: 28px;
  padding-right: 20px;
  padding-left: 6px;
  text-align: right;
}

.unit {
  position: absolute;
  top: 50%;
  right: 7px;
  color: var(--ink-400);
  font-size: var(--text-xs);
  transform: translateY(-50%);
  pointer-events: none;
}

.split-foot {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 6px;
  padding: 2px 2px 2px 8px;
  border-radius: var(--r-md);
  font-size: var(--text-xs);
  font-weight: 500;
}

.foot-text {
  display: inline-flex;
  align-items: center;
  gap: 6px;
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
