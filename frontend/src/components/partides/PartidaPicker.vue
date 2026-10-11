<script setup lang="ts">
import { computed, nextTick, ref, watch } from 'vue'

import type { Partida } from '../../api/types'
import {
  LEVEL_LABELS,
  LEVELS,
  type Level,
  formatEuros,
  fundTone,
  lineLevels,
  lineTitle,
  lineYears,
  matches,
  searchText,
  shortCode,
} from '../../partides'
import AppIcon from '../AppIcon.vue'

/**
 * The budget as a map to pick from.
 *
 * Lines sit in blocks — by concept (esfer@'s own headings) or by fund — and
 * each carries its fund's colour as a stripe, so "the Motxilles one" is found
 * by colour before it is read. The invoice's school year leads: lines of
 * other years stay visible but step back. Search, fund, year and level narrow
 * the map; the keyboard walks what is left.
 */
const props = defineProps<{
  partides: Partida[]
  selected: number[]
  /** Jev's probability per line id, for the ones it ranked. */
  suggested: Record<number, number>
  /** `25-26`: the invoice's school year. */
  invoiceYear: string
  disabled?: boolean
}>()
const emit = defineEmits<{ toggle: [id: number] }>()

const query = ref('')
const groupBy = ref<'concepte' | 'fons'>('concepte')
const year = ref<'factura' | 'tots' | string>('factura')
const levels = ref<Level[]>([])
const funds = ref<string[]>([])
const withIncome = ref(false)
const onlyFunded = ref(false)
const search = ref<HTMLInputElement | null>(null)
const cursor = ref(-1)

const byCode = computed(() => new Map(props.partides.map((p) => [p.codi, p])))

interface Line {
  partida: Partida
  title: string
  years: string[]
  levels: Level[]
  haystack: string
  tone: ReturnType<typeof fundTone>
  /** Of another school year than the invoice's: shown, but quieter. */
  aside: boolean
}

const lines = computed<Line[]>(() =>
  props.partides
    .filter((p) => !p.te_fills && !p.retirada)
    .filter((p) => withIncome.value || p.tipus === 'despesa')
    .map((p) => {
      const years = lineYears(p.nom)
      return {
        partida: p,
        title: lineTitle(p.nom),
        years,
        levels: lineLevels(p.nom),
        haystack: searchText(p, p.codi_pare ? byCode.value.get(p.codi_pare) : undefined),
        tone: fundTone(p.fons),
        aside: Boolean(props.invoiceYear) && years.length > 0 && !years.includes(props.invoiceYear),
      }
    }),
)

/** Every year any line names, newest first: the year filter's options. */
const years = computed(() =>
  [...new Set(lines.value.flatMap((line) => line.years))].sort().reverse(),
)

const fundLegend = computed(() => {
  const counts = new Map<string, { label: string; count: number }>()
  for (const line of lines.value) {
    const entry = counts.get(line.partida.fons) ?? { label: line.partida.fons_label, count: 0 }
    entry.count += 1
    counts.set(line.partida.fons, entry)
  }
  return [...counts.entries()]
    .map(([fons, { label, count }]) => ({ fons, label, count, tone: fundTone(fons) }))
    .sort((a, b) => (a.fons === '' ? 1 : b.fons === '' ? -1 : b.count - a.count))
})

const visible = computed(() =>
  lines.value.filter((line) => {
    const p = line.partida
    if (props.selected.includes(p.id)) return true
    if (query.value && !matches(line.haystack, query.value)) return false
    if (funds.value.length && !funds.value.includes(p.fons)) return false
    if (levels.value.length && !line.levels.some((level) => levels.value.includes(level))) return false
    if (onlyFunded.value && p.import_pressupost <= 0 && p.factures === 0) return false
    const wanted = year.value === 'factura' ? props.invoiceYear : year.value
    if (year.value !== 'tots' && wanted && line.years.length && !line.years.includes(wanted)) {
      // "Curs de la factura" keeps other years findable by search, just not by browsing.
      return year.value === 'factura' && Boolean(query.value)
    }
    return true
  }),
)

interface Block {
  key: string
  title: string
  code: string
  budget: number | null
  tone: ReturnType<typeof fundTone> | null
  lines: Line[]
  /** Lines with no budget, no invoices and no year: folded away until asked for. */
  quiet: Line[]
  /** A catch-all of lines without a heading: after the real concepts. */
  loose?: boolean
}

const unfolded = ref(new Set<string>())

/** A line nobody budgeted or used, and not tied to a year: rarely the one. */
function isQuiet(line: Line) {
  const p = line.partida
  return (
    p.import_pressupost <= 0 &&
    p.factures === 0 &&
    line.years.length === 0 &&
    !props.selected.includes(p.id) &&
    props.suggested[p.id] === undefined
  )
}

const CHAPTERS: Record<string, string> = {
  '2': 'Altres despeses corrents',
  '4': 'Transferències',
  '6': 'Inversions',
}

const blocks = computed<Block[]>(() => {
  const map = new Map<string, Block>()
  const narrowed = Boolean(query.value || funds.value.length || levels.value.length)
  const add = (key: string, make: () => Omit<Block, 'lines' | 'quiet'>, line: Line) => {
    let block = map.get(key)
    if (!block) {
      block = { ...make(), lines: [], quiet: [] }
      map.set(key, block)
    }
    if (!narrowed && !unfolded.value.has(key) && isQuiet(line)) block.quiet.push(line)
    else block.lines.push(line)
  }
  for (const line of visible.value) {
    const p = line.partida
    if (groupBy.value === 'fons') {
      add(p.fons || '~', () => ({ key: p.fons || '~', title: p.fons_label, code: '', budget: null, tone: line.tone }), line)
      continue
    }
    const parent = p.codi_pare ? byCode.value.get(p.codi_pare) : undefined
    if (parent) {
      add(parent.codi, () => ({
        key: parent.codi,
        title: parent.nom,
        code: parent.codi,
        budget: parent.import_pressupost,
        tone: null,
      }), line)
    } else {
      const chapter = p.tipus === 'ingres' ? 'I' : (p.codi.match(/^D\/(\d)/)?.[1] ?? '2')
      add(`chapter-${chapter}`, () => ({
        key: `chapter-${chapter}`,
        title: chapter === 'I' ? 'Ingressos' : (CHAPTERS[chapter] ?? 'Altres partides'),
        code: '',
        budget: null,
        tone: null,
        loose: true,
      }), line)
    }
  }
  const list = [...map.values()].filter((block) => block.lines.length || block.quiet.length)
  for (const block of list) {
    // The invoice's year first, then esfer@'s order.
    block.lines.sort((a, b) => Number(a.aside) - Number(b.aside) || a.partida.ordre - b.partida.ordre)
  }
  if (groupBy.value === 'fons') list.sort((a, b) => (a.key === '~' ? 1 : b.key === '~' ? -1 : b.lines.length - a.lines.length))
  // esfer@'s order for real concepts; the loose catch-alls after them.
  else list.sort((a, b) => Number(Boolean(a.loose)) - Number(Boolean(b.loose)))
  return list
})

/** What the arrow keys walk, in reading order. */
const flat = computed(() => blocks.value.flatMap((block) => block.lines.map((line) => line.partida.id)))

watch([query, funds, levels, year, groupBy], () => {
  cursor.value = query.value ? 0 : -1
})

function toggleIn<T>(list: T[], value: T): T[] {
  return list.includes(value) ? list.filter((item) => item !== value) : [...list, value]
}

function onSearchKey(event: KeyboardEvent) {
  const count = flat.value.length
  if (!count) return
  if (event.key === 'ArrowDown') {
    event.preventDefault()
    cursor.value = Math.min(count - 1, cursor.value + 1)
  } else if (event.key === 'ArrowUp') {
    event.preventDefault()
    cursor.value = Math.max(0, cursor.value - 1)
  } else if (event.key === 'Enter' && !(event.metaKey || event.ctrlKey) && cursor.value >= 0) {
    event.preventDefault()
    emit('toggle', flat.value[cursor.value])
  } else if (event.key === 'Escape' && query.value) {
    event.stopPropagation()
    query.value = ''
  } else {
    return
  }
  void nextTick(() =>
    document
      .querySelector(`[data-partida="${flat.value[cursor.value]}"]`)
      ?.scrollIntoView({ block: 'nearest' }),
  )
}

function used(p: Partida) {
  return p.import_pressupost > 0 ? Math.min(1, p.imputat / p.import_pressupost) : p.imputat > 0 ? 1 : 0
}

function focusSearch() {
  search.value?.focus()
  search.value?.select()
}

function reset() {
  query.value = ''
  funds.value = []
  levels.value = []
  year.value = 'factura'
  onlyFunded.value = false
}

defineExpose({ focusSearch })
</script>

<template>
  <div class="picker">
    <div class="toolbar">
      <label class="search">
        <AppIcon name="search" :size="14" />
        <input
          ref="search"
          v-model="query"
          class="search-input"
          type="search"
          placeholder="Cerca una partida, un codi, un fons…"
          aria-label="Cerca partides"
          :aria-activedescendant="cursor >= 0 ? `partida-${flat[cursor]}` : undefined"
          @keydown="onSearchKey"
        />
        <kbd class="kbd">/</kbd>
      </label>

      <div class="seg" role="radiogroup" aria-label="Agrupa per">
        <button
          type="button"
          role="radio"
          :aria-checked="groupBy === 'concepte'"
          :class="{ on: groupBy === 'concepte' }"
          @click="groupBy = 'concepte'"
        >
          Concepte
        </button>
        <button
          type="button"
          role="radio"
          :aria-checked="groupBy === 'fons'"
          :class="{ on: groupBy === 'fons' }"
          @click="groupBy = 'fons'"
        >
          Fons
        </button>
      </div>
    </div>

    <div class="facets">
      <div class="facet" role="group" aria-label="Curs">
        <button
          type="button"
          class="chip"
          :class="{ on: year === 'factura' }"
          :title="invoiceYear ? `Les partides del curs ${invoiceYear} i les que no en tenen` : ''"
          @click="year = 'factura'"
        >
          Curs de la factura<span v-if="invoiceYear" class="mono"> · {{ invoiceYear }}</span>
        </button>
        <button
          v-for="option in years"
          :key="option"
          type="button"
          class="chip mono"
          :class="{ on: year === option }"
          @click="year = year === option ? 'factura' : option"
        >
          {{ option }}
        </button>
        <button type="button" class="chip" :class="{ on: year === 'tots' }" @click="year = 'tots'">Tots</button>
      </div>
      <span class="facet-sep" />
      <div class="facet" role="group" aria-label="Nivell">
        <button
          v-for="level in LEVELS"
          :key="level"
          type="button"
          class="chip"
          :class="{ on: levels.includes(level) }"
          :title="LEVEL_LABELS[level]"
          @click="levels = toggleIn(levels, level)"
        >
          {{ level }}
        </button>
      </div>
      <span class="facet-sep" />
      <label class="check">
        <input v-model="onlyFunded" type="checkbox" />
        Amb pressupost
      </label>
      <label class="check">
        <input v-model="withIncome" type="checkbox" />
        Ingressos
      </label>
    </div>

    <div class="legend" role="group" aria-label="Fons">
      <button
        v-for="fund in fundLegend"
        :key="fund.fons || 'ordinari'"
        type="button"
        class="fund"
        :class="{ on: funds.includes(fund.fons), off: funds.length && !funds.includes(fund.fons) }"
        :style="{ '--tone': fund.tone.solid, '--tone-soft': fund.tone.soft }"
        @click="funds = toggleIn(funds, fund.fons)"
      >
        <span class="fund-dot" />
        {{ fund.label }}
        <span class="fund-count">{{ fund.count }}</span>
      </button>
    </div>

    <div v-if="blocks.length" class="map" role="listbox" aria-multiselectable="true" aria-label="Partides">
      <section v-for="block in blocks" :key="block.key" class="block">
        <header class="block-head" :style="block.tone ? { '--tone': block.tone.solid } : undefined">
          <span v-if="block.tone" class="fund-dot" />
          <span class="block-title">{{ block.title }}</span>
          <span v-if="block.budget" class="block-budget mono">{{ formatEuros(block.budget) }}</span>
        </header>
        <button
          v-for="line in block.lines"
          :id="`partida-${line.partida.id}`"
          :key="line.partida.id"
          :data-partida="line.partida.id"
          type="button"
          role="option"
          class="line"
          :class="{
            'is-on': selected.includes(line.partida.id),
            'is-aside': line.aside && !selected.includes(line.partida.id),
            'is-cursor': flat[cursor] === line.partida.id,
            'is-suggested': suggested[line.partida.id] !== undefined,
          }"
          :aria-selected="selected.includes(line.partida.id)"
          :disabled="disabled"
          :style="{ '--tone': line.tone.solid, '--tone-soft': line.tone.soft }"
          :title="line.partida.context ? `${line.partida.nom}\n\n${line.partida.context}` : line.partida.nom"
          @click="emit('toggle', line.partida.id)"
        >
          <span class="line-main">
            <span class="line-title">{{ line.title }}</span>
            <span class="line-tags">
              <span v-for="tag in line.years" :key="tag" class="tag tag-year mono">{{ tag }}</span>
              <span class="tag mono">{{ shortCode(line.partida.codi) }}</span>
              <span v-if="line.partida.context" class="tag tag-note" aria-label="Té context">
                <AppIcon name="message" :size="10" />
              </span>
              <span v-if="suggested[line.partida.id] !== undefined" class="tag tag-ai">
                <AppIcon name="sparkles" :size="10" />
                {{ Math.round(suggested[line.partida.id] * 100) }} %
              </span>
            </span>
          </span>
          <span class="line-side">
            <span class="line-budget mono">{{ formatEuros(line.partida.import_pressupost) }}</span>
            <span
              class="meter"
              :title="`Imputat ${formatEuros(line.partida.imputat, 2)} en ${line.partida.factures} factures`"
            >
              <span
                :class="{ over: line.partida.imputat > line.partida.import_pressupost }"
                :style="{ width: `${used(line.partida) * 100}%` }"
              />
            </span>
          </span>
          <span class="line-check" aria-hidden="true">
            <AppIcon v-if="selected.includes(line.partida.id)" name="check" :size="12" />
          </span>
        </button>
        <button
          v-if="block.quiet.length"
          type="button"
          class="more"
          @click="unfolded = new Set([...unfolded, block.key])"
        >
          <AppIcon name="plus" :size="11" />
          {{ block.quiet.length }} {{ block.quiet.length === 1 ? 'partida' : 'partides' }} sense pressupost ni ús
        </button>
      </section>
    </div>
    <div v-else class="empty-map">
      <p>Cap partida amb aquests filtres.</p>
      <button type="button" class="btn btn-outline btn-sm" @click="reset">Treu els filtres</button>
    </div>
  </div>
</template>

<style scoped>
.picker {
  display: grid;
  grid-template-rows: auto auto auto minmax(0, 1fr);
  gap: 8px;
  min-height: 0;
}

.toolbar {
  display: flex;
  gap: 8px;
}

.search {
  display: flex;
  flex: 1;
  align-items: center;
  gap: 8px;
  height: 32px;
  padding: 0 8px 0 10px;
  border: 1px solid var(--line-strong);
  border-radius: var(--r-md);
  background: var(--surface-0);
  color: var(--ink-400);
}

.search:focus-within {
  border-color: var(--accent-500);
  box-shadow: 0 0 0 3px var(--accent-100);
}

.search-input {
  flex: 1;
  min-width: 0;
  border: 0;
  outline: 0;
  background: none;
  color: var(--ink-900);
  font: inherit;
  font-size: var(--text-base);
}

.kbd {
  padding: 0 5px;
  border: 1px solid var(--line-strong);
  border-radius: var(--r-xs);
  color: var(--ink-400);
  font-family: var(--font-mono);
  font-size: var(--text-xs);
  line-height: 16px;
}

.seg {
  display: inline-flex;
  padding: 2px;
  border: 1px solid var(--line-strong);
  border-radius: var(--r-md);
  background: var(--surface-1);
}

.seg button {
  padding: 3px 10px;
  border: 0;
  border-radius: var(--r-sm);
  background: none;
  color: var(--ink-500);
  font: inherit;
  font-size: var(--text-sm);
  font-weight: 500;
  cursor: pointer;
}

.seg button.on {
  background: var(--surface-0);
  color: var(--ink-900);
  box-shadow: var(--shadow-xs);
}

/* ── Facets ───────────────────────────────────────────────────────────── */
.facets {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 6px;
}

.facet {
  display: flex;
  flex-wrap: wrap;
  gap: 3px;
}

.facet-sep {
  width: 1px;
  height: 16px;
  background: var(--line);
}

.chip {
  padding: 2px 8px;
  border: 1px solid var(--line);
  border-radius: var(--r-sm);
  background: var(--surface-0);
  color: var(--ink-500);
  font: inherit;
  font-size: var(--text-sm);
  cursor: pointer;
}

.chip:hover {
  border-color: var(--line-strong);
  color: var(--ink-900);
}

.chip.on {
  border-color: var(--accent-300);
  background: var(--accent-50);
  color: var(--accent-700);
  font-weight: 600;
}

.check {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  color: var(--ink-500);
  font-size: var(--text-sm);
  cursor: pointer;
}

.check input {
  accent-color: var(--accent-700);
}

/* ── Fund legend ──────────────────────────────────────────────────────── */
.legend {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
}

.fund {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 2px 8px 2px 6px;
  border: 1px solid var(--line);
  border-radius: var(--r-sm);
  background: var(--surface-0);
  color: var(--ink-700);
  font: inherit;
  font-size: var(--text-sm);
  cursor: pointer;
  transition: opacity 0.12s ease;
}

.fund:hover {
  border-color: var(--tone);
}

.fund.on {
  border-color: var(--tone);
  background: var(--tone-soft);
  font-weight: 600;
}

.fund.off {
  opacity: 0.55;
}

.fund-dot {
  width: 8px;
  height: 8px;
  flex-shrink: 0;
  border-radius: 2px;
  background: var(--tone);
}

.fund-count {
  color: var(--ink-400);
  font-size: var(--text-xs);
  font-variant-numeric: tabular-nums;
}

/* ── The map ──────────────────────────────────────────────────────────── */
.map {
  min-height: 0;
  overflow-y: auto;
  padding: 2px 2px 12px;
  columns: 300px;
  column-gap: 10px;
}

.block {
  display: grid;
  gap: 3px;
  margin-bottom: 10px;
  padding: 8px;
  border: 1px solid var(--line);
  border-radius: var(--r-lg);
  background: var(--surface-0);
  break-inside: avoid;
}

.block-head {
  display: flex;
  align-items: baseline;
  gap: 6px;
  padding: 0 2px 4px;
}

.block-head .fund-dot {
  align-self: center;
}

.block-title {
  flex: 1;
  min-width: 0;
  color: var(--ink-700);
  font-size: var(--text-xs);
  font-weight: 600;
  letter-spacing: 0.03em;
  line-height: 1.3;
  text-transform: uppercase;
}

.block-budget {
  color: var(--ink-400);
  font-size: var(--text-xs);
}

.line {
  position: relative;
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto 14px;
  align-items: center;
  gap: 8px;
  width: 100%;
  padding: 5px 6px 5px 10px;
  border: 1px solid transparent;
  border-radius: var(--r-md);
  background: none;
  color: var(--ink-900);
  font: inherit;
  text-align: left;
  cursor: pointer;
}

/* The fund, as a stripe down the left edge. */
.line::before {
  content: '';
  position: absolute;
  top: 5px;
  bottom: 5px;
  left: 3px;
  width: 3px;
  border-radius: 2px;
  background: var(--tone);
}

.line:hover {
  background: var(--tone-soft);
}

.line.is-cursor {
  border-color: var(--accent-400);
}

.line.is-suggested {
  border-color: var(--ai-200);
  border-style: dashed;
}

.line.is-on {
  border-color: var(--tone);
  border-style: solid;
  background: var(--tone-soft);
}

.line.is-aside {
  opacity: 0.5;
}

.line.is-aside:hover {
  opacity: 1;
}

.line:disabled {
  cursor: default;
}

.line-main {
  display: grid;
  gap: 2px;
  min-width: 0;
}

.line-title {
  overflow: hidden;
  font-size: var(--text-sm);
  line-height: 1.3;
  text-overflow: ellipsis;
}

.line.is-on .line-title {
  font-weight: 600;
}

.line-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 3px;
}

.tag {
  display: inline-flex;
  align-items: center;
  gap: 2px;
  padding: 0 4px;
  border-radius: var(--r-xs);
  background: var(--surface-2);
  color: var(--ink-400);
  font-size: 10px;
  line-height: 15px;
}

.tag-year {
  background: var(--surface-3);
  color: var(--ink-700);
  font-weight: 600;
}

.tag-note {
  color: var(--accent-700);
}

.tag-ai {
  background: var(--ai-100);
  color: var(--ai-700);
  font-weight: 600;
}

.line-side {
  display: grid;
  justify-items: end;
  gap: 3px;
}

.line-budget {
  color: var(--ink-500);
  font-size: var(--text-xs);
}

.meter {
  width: 44px;
  height: 3px;
  overflow: hidden;
  border-radius: 2px;
  background: var(--surface-3);
}

.meter > span {
  display: block;
  height: 100%;
  background: var(--tone);
}

.meter > span.over {
  background: var(--danger-600);
}

.line-check {
  display: grid;
  place-items: center;
  width: 14px;
  height: 14px;
  border: 1px solid var(--line-strong);
  border-radius: var(--r-xs);
  color: #fff;
}

.line.is-on .line-check {
  border-color: var(--tone);
  background: var(--tone);
}

.more {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  justify-self: start;
  margin-top: 2px;
  padding: 2px 6px;
  border: 0;
  border-radius: var(--r-sm);
  background: none;
  color: var(--ink-400);
  font: inherit;
  font-size: var(--text-xs);
  cursor: pointer;
}

.more:hover {
  background: var(--surface-2);
  color: var(--accent-700);
}

.empty-map {
  display: grid;
  place-items: center;
  gap: 8px;
  padding: 40px 16px;
  color: var(--ink-400);
  font-size: var(--text-base);
}

@media (max-width: 720px) {
  .map {
    columns: 1;
  }
}
</style>
