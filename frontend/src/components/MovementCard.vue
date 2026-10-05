<script setup lang="ts">
import { computed } from 'vue'

import type { Movement } from '../api/types'
import { formatAmount, formatDate } from '../document-fields'
import { CATEGORIA_LABEL, SOURCE_LABEL, STATUS_LABEL } from '../matching'
import AppIcon from './AppIcon.vue'

/**
 * Everything a statement line carries, floating beside it. The list keeps to
 * what decides a match; this is where the rest lives. A line's «Detalls»
 * button opens it, and it can be dragged out of the way.
 */
const props = defineProps<{ movement: Movement; x: number; y: number; pinned: boolean }>()
const emit = defineEmits<{
  pin: []
  close: []
  enter: []
  leave: []
  move: [x: number, y: number]
}>()

const m = computed(() => props.movement)

const facts = computed(() =>
  (
    [
      ['Data', formatDate(m.value.data), true],
      ['Data valor', m.value.data_valor && m.value.data_valor !== m.value.data ? formatDate(m.value.data_valor) : '', true],
      ['Compte', m.value.compte, false],
      ['Tipus', m.value.tipus, false],
      ['Categoria', CATEGORIA_LABEL[m.value.categoria] ?? m.value.categoria, false],
      ['Font', SOURCE_LABEL[m.value.source] ?? m.value.source, false],
      ['Codi', m.value.codi, true],
      ['Ref. extracte', m.value.external_ref !== m.value.codi ? m.value.external_ref : '', true],
      ['Més dades', m.value.mes_dades, false],
      ['Núm. factura', m.value.num_factura_hint, true],
      ['CIF', m.value.cif_hint, true],
      ['IBAN', m.value.iban_hint, true],
      ['Saldo', m.value.saldo != null ? formatAmount(m.value.saldo) : '', true],
      [
        'Estat',
        `${STATUS_LABEL[m.value.match_status] ?? m.value.match_status}${m.value.confidence != null ? ` · ${m.value.confidence}` : ''}`,
        false,
      ],
      ['Factures', m.value.documents.join(', '), true],
    ] as [string, string, boolean][]
  ).filter(([, value]) => value),
)

/** The source's own line, minus what the facts above already say. */
const raw = computed(() => {
  const shown = new Set(facts.value.map(([, value]) => value).concat(m.value.concepte))
  return Object.entries(m.value.raw ?? {})
    .map(([key, value]) => [key, Array.isArray(value) ? value.filter((v) => v !== '').join(' · ') : String(value ?? '')] as const)
    .filter(([, value]) => value && !shown.has(value))
})

// ── Dragging a pinned card by its head ──────────────────────────────────────
let from: { x: number; y: number; px: number; py: number } | null = null

function onPointerDown(event: PointerEvent) {
  if (!props.pinned || (event.target as HTMLElement).closest('button')) return
  ;(event.currentTarget as HTMLElement).setPointerCapture(event.pointerId)
  from = { x: props.x, y: props.y, px: event.clientX, py: event.clientY }
}

function onPointerMove(event: PointerEvent) {
  if (from) emit('move', from.x + event.clientX - from.px, from.y + event.clientY - from.py)
}

function onPointerUp() {
  from = null
}
</script>

<template>
  <Teleport to="body">
    <div
      class="mcard"
      :class="{ pinned: props.pinned }"
      :style="{ left: `${props.x}px`, top: `${props.y}px` }"
      role="dialog"
      :aria-label="`Detall del moviment ${m.concepte}`"
      @mouseenter="emit('enter')"
      @mouseleave="emit('leave')"
    >
      <header
        class="mcard-head"
        @pointerdown="onPointerDown"
        @pointermove="onPointerMove"
        @pointerup="onPointerUp"
        @pointercancel="onPointerUp"
      >
        <span class="mcard-title">
          <span v-if="m.codi" class="code mono">{{ m.codi }}</span>
          <strong class="truncate">{{ m.concepte || 'Sense concepte' }}</strong>
          <span class="num" :class="{ in: m.import_value > 0 }">{{ formatAmount(m.import_value) }}</span>
        </span>
        <button
          class="tool"
          :class="{ on: props.pinned }"
          type="button"
          :title="props.pinned ? 'Fixada' : 'Fixa (P)'"
          :aria-pressed="props.pinned"
          @click="props.pinned ? emit('close') : emit('pin')"
        >
          <AppIcon name="pin" :size="13" />
        </button>
        <button v-if="props.pinned" class="tool" type="button" title="Tanca" @click="emit('close')">
          <AppIcon name="close" :size="13" />
        </button>
      </header>

      <dl class="facts">
        <template v-for="[label, value, mono] in facts" :key="label">
          <dt>{{ label }}</dt>
          <dd :class="{ mono }">{{ value }}</dd>
        </template>
      </dl>

      <section v-if="raw.length" class="raw">
        <h4>Línia original</h4>
        <dl class="facts">
          <template v-for="[key, value] in raw" :key="key">
            <dt>{{ key }}</dt>
            <dd class="mono">{{ value }}</dd>
          </template>
        </dl>
      </section>

      <p v-if="!props.pinned" class="hint muted">Prem P per fixar-la</p>
    </div>
  </Teleport>
</template>

<style scoped>
.mcard {
  position: fixed;
  z-index: 60;
  width: 300px;
  max-height: min(70vh, 520px);
  overflow-y: auto;
  display: grid;
  gap: 8px;
  padding: 0 12px 10px;
  background: var(--surface-0);
  border: 1px solid var(--line-strong);
  border-radius: var(--r-md);
  box-shadow: var(--shadow-md);
  font-size: var(--text-sm);
}

.mcard.pinned {
  border-color: var(--accent-500);
  z-index: 55;
}

.mcard-head {
  position: sticky;
  top: 0;
  display: flex;
  align-items: center;
  gap: 4px;
  margin: 0 -12px;
  padding: 7px 6px 7px 12px;
  background: var(--surface-1);
  border-bottom: 1px solid var(--line);
}

.pinned .mcard-head {
  cursor: move;
}

.mcard-title {
  display: flex;
  align-items: baseline;
  gap: 8px;
  flex: 1;
  min-width: 0;
}

.mcard-title strong {
  flex: 1;
  min-width: 0;
}

.mcard-title .code {
  flex: none;
  font-size: 12px;
  color: var(--ink-500);
}

.mcard-title .num {
  flex: none;
  font-weight: 600;
  font-variant-numeric: tabular-nums;
}

.mcard-title .num.in {
  color: var(--olive-700);
}

.tool {
  display: inline-grid;
  place-items: center;
  width: 24px;
  height: 24px;
  border: 0;
  border-radius: var(--r-sm);
  background: transparent;
  color: var(--ink-500);
  cursor: pointer;
}

.tool:hover {
  background: var(--surface-2);
  color: var(--ink-700);
}

.tool.on {
  color: var(--accent-700);
}

.facts {
  display: grid;
  grid-template-columns: auto minmax(0, 1fr);
  gap: 3px 10px;
  margin: 0;
}

.facts dt {
  color: var(--ink-400);
  white-space: nowrap;
}

.facts dd {
  margin: 0;
  overflow-wrap: anywhere;
  font-variant-numeric: tabular-nums;
}

.raw {
  display: grid;
  gap: 4px;
  padding-top: 8px;
  border-top: 1px dashed var(--line);
}

.raw h4 {
  margin: 0;
  font-size: var(--text-xs);
  font-weight: 600;
  letter-spacing: 0.06em;
  text-transform: uppercase;
  color: var(--ink-400);
}

.raw .facts {
  font-size: var(--text-xs);
}

.hint {
  margin: 0;
  font-size: var(--text-xs);
}
</style>
