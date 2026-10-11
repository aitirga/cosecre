<script setup lang="ts">
/**
 * A range filter as a chip: dates (with the periods a school thinks in —
 * this month, this term, this school year) or amounts. Empty, "+ Data";
 * set, "Data: Aquest curs" or "Import: 50 € – 200 €", with its own ×.
 */
import { computed, ref } from 'vue'

import { formatAmount, formatDate, parseAmount } from '../document-fields'
import AnchoredPopover from './AnchoredPopover.vue'
import AppIcon from './AppIcon.vue'
import type { IconName } from './icons'

const props = defineProps<{ label: string; kind: 'date' | 'amount'; icon?: IconName }>()
const from = defineModel<string>('from', { required: true })
const to = defineModel<string>('to', { required: true })

const open = ref(false)
const button = ref<HTMLButtonElement | null>(null)

// ── Periods ─────────────────────────────────────────────────────────────────
function iso(day: Date) {
  return `${day.getFullYear()}-${String(day.getMonth() + 1).padStart(2, '0')}-${String(day.getDate()).padStart(2, '0')}`
}
function monthEnd(year: number, month: number) {
  return new Date(year, month + 1, 0)
}

const PERIODS = computed(() => {
  const today = new Date()
  const y = today.getFullYear()
  const m = today.getMonth()
  const q = Math.floor(m / 3) * 3
  const course = m >= 8 ? y : y - 1
  return [
    { key: 'month', label: 'Aquest mes', range: [new Date(y, m, 1), monthEnd(y, m)] },
    { key: 'last-month', label: 'Mes passat', range: [new Date(y, m - 1, 1), monthEnd(y, m - 1)] },
    { key: 'quarter', label: 'Aquest trimestre', range: [new Date(y, q, 1), monthEnd(y, q + 2)] },
    { key: 'last-quarter', label: 'Trimestre passat', range: [new Date(y, q - 3, 1), monthEnd(y, q - 1)] },
    { key: 'course', label: 'Aquest curs', hint: `Set. ${course} – ag. ${course + 1}`, range: [new Date(course, 8, 1), new Date(course + 1, 7, 31)] },
    { key: 'last-course', label: 'Curs passat', hint: `Set. ${course - 1} – ag. ${course}`, range: [new Date(course - 1, 8, 1), new Date(course, 7, 31)] },
    { key: 'year', label: `Any ${y}`, range: [new Date(y, 0, 1), new Date(y, 11, 31)] },
    { key: 'last-year', label: `Any ${y - 1}`, range: [new Date(y - 1, 0, 1), new Date(y - 1, 11, 31)] },
  ].map((p) => ({ ...p, from: iso(p.range[0] as Date), to: iso(p.range[1] as Date) }))
})

const matchingPeriod = computed(() =>
  props.kind === 'date' ? PERIODS.value.find((p) => p.from === from.value && p.to === to.value) : undefined,
)

function pick(period: { from: string; to: string }) {
  from.value = period.from
  to.value = period.to
  open.value = false
}

// ── Amounts are typed the Catalan way ("1.234,50") and stored plainly ──────
const amountFrom = ref('')
const amountTo = ref('')
function amountText(value: string) {
  return value ? formatAmount(Number(value)).replace(' €', '') : ''
}
function commitAmount(which: 'from' | 'to', text: string) {
  const parsed = text.trim() ? parseAmount(text) : null
  const value = parsed == null ? '' : String(parsed)
  if (which === 'from') from.value = value
  else to.value = value
}

function toggle() {
  open.value = !open.value
  if (open.value && props.kind === 'amount') {
    amountFrom.value = amountText(from.value)
    amountTo.value = amountText(to.value)
  }
}

// ── What the chip says ──────────────────────────────────────────────────────
function shortDate(value: string) {
  return formatDate(value)
}
const summary = computed(() => {
  if (!from.value && !to.value) return ''
  if (matchingPeriod.value) return matchingPeriod.value.label
  if (props.kind === 'date') {
    if (from.value && to.value) return `${shortDate(from.value)} – ${shortDate(to.value)}`
    return from.value ? `des del ${shortDate(from.value)}` : `fins al ${shortDate(to.value)}`
  }
  const a = from.value ? formatAmount(Number(from.value)) : ''
  const b = to.value ? formatAmount(Number(to.value)) : ''
  if (a && b) return `${a} – ${b}`
  return a ? `≥ ${a}` : `≤ ${b}`
})

function clear() {
  from.value = ''
  to.value = ''
}
</script>

<template>
  <span class="chip" :class="{ set: summary, open }">
    <button ref="button" class="chip-main" type="button" :aria-expanded="open" @click="toggle">
      <AppIcon v-if="!summary" name="plus" :size="12" class="chip-icon" />
      <AppIcon v-else-if="icon" :name="icon" :size="12" class="chip-icon" />
      <span>{{ label }}</span>
      <template v-if="summary">
        <span class="chip-sep" aria-hidden="true" />
        <span class="chip-value truncate">{{ summary }}</span>
      </template>
      <AppIcon v-else name="chevron" :size="11" class="chip-caret" />
    </button>
    <button
      v-if="summary"
      class="chip-clear"
      type="button"
      :aria-label="`Treu el filtre ${label}`"
      :title="`Treu el filtre ${label}`"
      @click="clear"
    >
      <AppIcon name="close" :size="11" />
    </button>
  </span>

  <AnchoredPopover v-if="open" :anchor="button" :label="label" :width="kind === 'date' ? 300 : 260" @close="open = false">
    <div class="menu">
      <template v-if="kind === 'date'">
        <div class="menu-head">Període</div>
        <div class="periods">
          <button
            v-for="period in PERIODS"
            :key="period.key"
            class="period"
            :class="{ on: matchingPeriod?.key === period.key }"
            type="button"
            @click="pick(period)"
          >
            <span>{{ period.label }}</span>
            <span v-if="period.hint" class="period-hint">{{ period.hint }}</span>
          </button>
        </div>
        <div class="menu-head">O entre dues dates</div>
        <div class="custom">
          <label>
            <span>Des de</span>
            <input v-model="from" class="input" type="date" :max="to || undefined" />
          </label>
          <label>
            <span>Fins a</span>
            <input v-model="to" class="input" type="date" :min="from || undefined" />
          </label>
        </div>
      </template>

      <template v-else>
        <div class="menu-head">Import</div>
        <div class="custom">
          <label>
            <span>Mínim</span>
            <span class="amount">
              <input
                v-model="amountFrom"
                class="input input-mono"
                inputmode="decimal"
                placeholder="0,00"
                @change="commitAmount('from', amountFrom)"
                @keydown.enter="commitAmount('from', amountFrom); open = false"
              />
              <span class="unit">€</span>
            </span>
          </label>
          <label>
            <span>Màxim</span>
            <span class="amount">
              <input
                v-model="amountTo"
                class="input input-mono"
                inputmode="decimal"
                placeholder="Sense límit"
                @change="commitAmount('to', amountTo)"
                @keydown.enter="commitAmount('to', amountTo); open = false"
              />
              <span class="unit">€</span>
            </span>
          </label>
        </div>
      </template>

      <button v-if="summary" class="menu-foot" type="button" @click="clear(); open = false">Treu el filtre</button>
    </div>
  </AnchoredPopover>
</template>

<style scoped>
/* The chip matches FilterChip's; kept local so each stays one readable file. */
.chip {
  display: inline-flex;
  align-items: stretch;
  max-width: 100%;
  height: 30px;
  border: 1px dashed var(--line-strong);
  border-radius: var(--r-full);
  background: var(--surface-0);
  color: var(--ink-500);
  transition:
    border-color 0.12s ease,
    background 0.12s ease;
}

.chip:hover,
.chip.open {
  border-color: var(--accent-400);
  color: var(--ink-700);
}

.chip.set {
  border-style: solid;
  border-color: var(--accent-200);
  background: var(--accent-50);
  color: var(--accent-800);
}

.chip-main {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  min-width: 0;
  padding: 0 11px 0 10px;
  border: 0;
  border-radius: var(--r-full);
  background: none;
  font: inherit;
  font-size: var(--text-sm);
  font-weight: 500;
  color: inherit;
  cursor: pointer;
}

.chip.set .chip-main {
  padding-right: 4px;
}

.chip-main:focus-visible,
.chip-clear:focus-visible {
  outline: 2px solid var(--accent-500);
  outline-offset: 1px;
}

.chip-icon {
  flex: none;
  opacity: 0.8;
}

.chip-caret {
  flex: none;
  transform: rotate(90deg);
  opacity: 0.55;
}

.chip-sep {
  width: 1px;
  height: 12px;
  margin: 0 1px;
  background: var(--accent-200);
}

.chip-value {
  max-width: 200px;
  font-weight: 600;
}

.chip-clear {
  display: grid;
  place-items: center;
  width: 22px;
  margin: 3px 3px 3px 0;
  padding: 0;
  border: 0;
  border-radius: var(--r-full);
  background: none;
  color: var(--accent-700);
  cursor: pointer;
}

.chip-clear:hover {
  background: var(--accent-100);
}

.menu {
  display: grid;
  gap: 2px;
  padding: 4px;
}

.menu-head {
  padding: 6px 8px 4px;
  font-size: var(--text-xs);
  font-weight: 600;
  letter-spacing: 0.06em;
  text-transform: uppercase;
  color: var(--ink-400);
}

.periods {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 4px;
  padding: 0 4px 6px;
}

.period {
  display: grid;
  gap: 1px;
  padding: 7px 9px;
  border: 1px solid var(--line);
  border-radius: var(--r-md);
  background: var(--surface-0);
  font: inherit;
  font-size: var(--text-sm);
  font-weight: 500;
  text-align: left;
  color: var(--ink-700);
  cursor: pointer;
}

.period:hover {
  border-color: var(--accent-300);
  background: var(--accent-50);
}

.period.on {
  border-color: var(--accent-400);
  background: var(--accent-50);
  color: var(--accent-800);
  font-weight: 600;
}

.period-hint {
  font-size: var(--text-xs);
  font-weight: 400;
  color: var(--ink-400);
}

.custom {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 8px;
  padding: 0 4px 6px;
}

.custom label {
  display: grid;
  gap: 3px;
  min-width: 0;
  font-size: var(--text-xs);
  color: var(--ink-500);
}

.custom .input {
  width: 100%;
  min-width: 0;
  height: 30px;
  padding: 4px 8px;
  font-size: var(--text-sm);
}

.amount {
  position: relative;
  display: block;
}

.amount .input {
  padding-right: 22px;
  text-align: right;
}

.unit {
  position: absolute;
  top: 50%;
  right: 8px;
  transform: translateY(-50%);
  color: var(--ink-400);
  font-size: var(--text-sm);
}

.menu-foot {
  margin-top: 2px;
  padding: 8px;
  border: 0;
  border-top: 1px solid var(--line);
  background: none;
  font: inherit;
  font-size: var(--text-sm);
  color: var(--ink-500);
  text-align: left;
  cursor: pointer;
}

.menu-foot:hover {
  color: var(--danger-700);
}
</style>
