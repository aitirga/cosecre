<script setup lang="ts">
/**
 * One filter, as a chip. Empty, it is a quiet dashed "+ Tipus"; set, it fills
 * in and says what it is set to — "Tipus: Factura" — with its own ×.
 *
 * The menu lists every option with how many rows it would leave, so a choice
 * that empties the table is visible before it is made.
 */
import { computed, nextTick, ref, watch } from 'vue'

import AnchoredPopover from './AnchoredPopover.vue'
import AppIcon from './AppIcon.vue'
import type { IconName } from './icons'

export interface FilterOption {
  value: string
  label: string
  /** A short line under the label, for options that need explaining. */
  hint?: string
}

const props = defineProps<{
  label: string
  options: readonly FilterOption[]
  icon?: IconName
  /** Rows each option would leave; omit to show no counts. */
  count?: (value: string) => number
}>()
const model = defineModel<string>({ required: true })

const open = ref(false)
const button = ref<HTMLButtonElement | null>(null)
const list = ref<HTMLElement | null>(null)
const query = ref('')
const active = ref(0)

const selected = computed(() => props.options.find((option) => option.value === model.value))
const searchable = computed(() => props.options.length > 8)

const shown = computed(() => {
  const term = query.value.trim().toLowerCase()
  return term ? props.options.filter((o) => o.label.toLowerCase().includes(term)) : props.options
})

/** Counts are worked out once per opening, not on every render. */
const counts = ref<Map<string, number>>(new Map())

async function toggle() {
  open.value = !open.value
  if (!open.value) return
  query.value = ''
  counts.value = new Map(props.count ? props.options.map((o) => [o.value, props.count!(o.value)]) : [])
  active.value = Math.max(0, shown.value.findIndex((o) => o.value === model.value))
  await nextTick()
  ;(list.value?.querySelector('input, [role="option"]') as HTMLElement | null)?.focus()
}

function choose(value: string) {
  // Picking what is already picked clears it — the menu is also an off switch.
  model.value = value === model.value ? '' : value
  open.value = false
  button.value?.focus()
}

function clear() {
  model.value = ''
}

watch(query, () => (active.value = 0))

function onKey(event: KeyboardEvent) {
  const total = shown.value.length
  if (!total) return
  if (event.key === 'ArrowDown') {
    event.preventDefault()
    active.value = (active.value + 1) % total
  } else if (event.key === 'ArrowUp') {
    event.preventDefault()
    active.value = (active.value - 1 + total) % total
  } else if (event.key === 'Enter') {
    event.preventDefault()
    const option = shown.value[active.value]
    if (option) choose(option.value)
    return
  } else {
    return
  }
  void nextTick(() =>
    (list.value?.querySelectorAll('[role="option"]')[active.value] as HTMLElement | undefined)?.scrollIntoView({
      block: 'nearest',
    }),
  )
}
</script>

<template>
  <span class="chip" :class="{ set: selected, open }">
    <button
      ref="button"
      class="chip-main"
      type="button"
      :aria-expanded="open"
      aria-haspopup="listbox"
      @click="toggle"
    >
      <AppIcon v-if="!selected" name="plus" :size="12" class="chip-icon" />
      <AppIcon v-else-if="icon" :name="icon" :size="12" class="chip-icon" />
      <span class="chip-label">{{ label }}</span>
      <template v-if="selected">
        <span class="chip-sep" aria-hidden="true" />
        <span class="chip-value truncate">{{ selected.label }}</span>
      </template>
      <AppIcon v-else name="chevron" :size="11" class="chip-caret" />
    </button>
    <button
      v-if="selected"
      class="chip-clear"
      type="button"
      :aria-label="`Treu el filtre ${label}`"
      :title="`Treu el filtre ${label}`"
      @click="clear"
    >
      <AppIcon name="close" :size="11" />
    </button>
  </span>

  <AnchoredPopover v-if="open" :anchor="button" :label="label" @close="open = false">
    <div ref="list" class="menu" @keydown="onKey">
      <div class="menu-head">{{ label }}</div>
      <div v-if="searchable" class="menu-search">
        <AppIcon name="search" :size="13" />
        <input v-model="query" type="text" :placeholder="`Cerca ${label.toLowerCase()}…`" />
      </div>
      <div role="listbox" :aria-label="label">
        <div
          v-for="(option, index) in shown"
          :key="option.value"
          role="option"
          tabindex="-1"
          class="option"
          :class="{ on: option.value === model, active: index === active, zero: counts.get(option.value) === 0 }"
          :aria-selected="option.value === model"
          @click="choose(option.value)"
          @mousemove="active = index"
        >
          <span class="check" aria-hidden="true">
            <AppIcon v-if="option.value === model" name="check" :size="13" />
          </span>
          <span class="option-text">
            <span class="option-label">{{ option.label }}</span>
            <span v-if="option.hint" class="option-hint">{{ option.hint }}</span>
          </span>
          <span v-if="counts.has(option.value)" class="option-count">{{ counts.get(option.value) }}</span>
        </div>
        <p v-if="!shown.length" class="menu-empty">Cap opció coincideix.</p>
      </div>
      <button v-if="selected" class="menu-foot" type="button" @click="choose(model)">
        Treu el filtre
      </button>
    </div>
  </AnchoredPopover>
</template>

<style scoped>
/* ── The chip ─────────────────────────────────────────────────────────── */
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
  max-width: 180px;
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

/* ── The menu ─────────────────────────────────────────────────────────── */
.menu {
  display: grid;
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

.menu-search {
  display: flex;
  align-items: center;
  gap: 6px;
  margin: 2px 4px 4px;
  padding: 0 8px;
  border: 1px solid var(--line);
  border-radius: var(--r-md);
  color: var(--ink-400);
}

.menu-search input {
  flex: 1;
  min-width: 0;
  height: 28px;
  border: 0;
  outline: none;
  background: none;
  font: inherit;
  font-size: var(--text-base);
  color: var(--ink-900);
}

.option {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 7px 8px;
  border-radius: var(--r-md);
  font-size: var(--text-base);
  color: var(--ink-700);
  cursor: pointer;
  outline: none;
}

.option.active {
  background: var(--surface-2);
}

.option.on {
  color: var(--accent-800);
  font-weight: 600;
}

.option.zero:not(.on) {
  color: var(--ink-400);
}

.check {
  display: grid;
  place-items: center;
  flex: none;
  width: 14px;
  color: var(--accent-600);
}

.option-text {
  display: grid;
  flex: 1;
  min-width: 0;
}

.option-hint {
  font-size: var(--text-xs);
  font-weight: 400;
  color: var(--ink-400);
}

.option-count {
  flex: none;
  min-width: 22px;
  padding: 0 6px;
  border-radius: var(--r-full);
  background: var(--surface-2);
  font-size: var(--text-xs);
  font-weight: 600;
  line-height: 18px;
  text-align: center;
  font-variant-numeric: tabular-nums;
  color: var(--ink-500);
}

.option.on .option-count {
  background: var(--accent-100);
  color: var(--accent-700);
}

.menu-empty {
  padding: 10px 8px;
  font-size: var(--text-sm);
  color: var(--ink-400);
}

.menu-foot {
  margin-top: 4px;
  padding: 8px;
  border: 0;
  border-top: 1px solid var(--line);
  border-radius: 0 0 var(--r-md) var(--r-md);
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
