<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { useQuery } from '@tanstack/vue-query'
import { RouterLink } from 'vue-router'

import { api } from '../api/client'
import { formatAmount, formatDate } from '../document-fields'
import AppIcon from './AppIcon.vue'

/**
 * A register entry floating beside the bank line it paid: its sheet row, field
 * by field, and the original. Dragged by its head, closed from it.
 */
const props = defineProps<{ reference: string; x: number; y: number }>()
const emit = defineEmits<{ close: []; move: [x: number, y: number] }>()

const documentQuery = useQuery({
  queryKey: computed(() => ['document', props.reference]),
  queryFn: () => api.getDocument(props.reference),
})
const doc = computed(() => documentQuery.data.value ?? null)

const facts = computed(() => {
  const d = doc.value
  if (!d) return []
  return (
    [
      ['Proveïdor', d.proveidor, false],
      ['CIF', d.cif_proveidor, true],
      ['Data factura', formatDate(d.data_factura), true],
      ['Tipus', d.tipus_document, false],
      ['Descripció', d.descripcio, false],
      ['Per a què', d.descripcio_compra, false],
      ['Pressupost', d.pressupost_afectat, false],
      ['Pagament', d.pagament, false],
      ['Mètode', d.metode_pagament, false],
      ['Data pagament', formatDate(d.data_pagament), true],
      ['IBAN', d.compte_corrent, true],
      ['Responsable', d.responsable_nom, false],
      ['Validat', d.validat ? 'Sí' : 'No', false],
      ['Referència', d.num_doc_intern, true],
    ] as [string, string | null | undefined, boolean][]
  ).filter(([, value]) => value)
})

// ── The original, fetched once the entry says it has one ────────────────────
const original = ref<{ url: string; type: string } | null>(null)
watch(
  () => doc.value?.file_url,
  async (url) => {
    if (!url || original.value) return
    try {
      original.value = await api.getDocumentFile(props.reference)
    } catch {
      original.value = null
    }
  },
  { immediate: true },
)
onBeforeUnmount(() => {
  if (original.value) URL.revokeObjectURL(original.value.url)
})

function openOriginal() {
  if (original.value) window.open(original.value.url, '_blank', 'noopener')
}

// ── Dragging by the head ────────────────────────────────────────────────────
let from: { x: number; y: number; px: number; py: number } | null = null

function onPointerDown(event: PointerEvent) {
  if ((event.target as HTMLElement).closest('button, a')) return
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
      class="dcard"
      :style="{ left: `${props.x}px`, top: `${props.y}px` }"
      role="dialog"
      :aria-label="`Registre ${doc?.num_factura || props.reference}`"
    >
      <header
        class="dcard-head"
        @pointerdown="onPointerDown"
        @pointermove="onPointerMove"
        @pointerup="onPointerUp"
        @pointercancel="onPointerUp"
      >
        <span class="dcard-kind"><AppIcon name="invoice" :size="12" /> Registre</span>
        <span class="dcard-title">
          <strong class="truncate">{{ doc?.num_factura || 'Sense número' }}</strong>
          <span v-if="doc" class="num">{{ formatAmount(doc.import) }}</span>
        </span>
        <button class="tool" type="button" title="Tanca" @click="emit('close')">
          <AppIcon name="close" :size="13" />
        </button>
      </header>

      <p v-if="documentQuery.isLoading.value" class="muted">Carregant…</p>
      <p v-else-if="!doc" class="muted">Aquest document ja no és al registre.</p>
      <template v-else>
        <button
          v-if="original && original.type.startsWith('image/')"
          class="thumb"
          type="button"
          title="Obre l'original"
          @click="openOriginal"
        >
          <img :src="original.url" alt="Original" />
        </button>

        <dl class="facts">
          <template v-for="[label, value, mono] in facts" :key="label">
            <dt>{{ label }}</dt>
            <dd :class="{ mono }">{{ value }}</dd>
          </template>
        </dl>

        <div class="links">
          <button v-if="original" class="btn btn-ghost btn-sm" type="button" @click="openOriginal">
            <AppIcon name="image" :size="13" /> Original
          </button>
          <RouterLink class="btn btn-ghost btn-sm" :to="{ name: 'document', params: { internalDocNumber: doc.num_doc_intern } }">
            <AppIcon name="external" :size="13" /> Obre al registre
          </RouterLink>
        </div>
      </template>
    </div>
  </Teleport>
</template>

<style scoped>
.dcard {
  position: fixed;
  z-index: 56;
  width: 320px;
  max-height: min(75vh, 560px);
  overflow-y: auto;
  display: grid;
  gap: 8px;
  padding: 0 12px 10px;
  background: var(--surface-0);
  border: 1px solid var(--accent-200);
  border-left: 3px solid var(--accent-700);
  border-radius: var(--r-md);
  box-shadow: var(--shadow-md);
  font-size: var(--text-sm);
}

.dcard-head {
  position: sticky;
  top: 0;
  display: flex;
  align-items: center;
  gap: 8px;
  margin: 0 -12px;
  padding: 7px 6px 7px 12px;
  background: var(--accent-50);
  border-bottom: 1px solid var(--accent-200);
  cursor: move;
}

.dcard-kind {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  flex: none;
  font-size: var(--text-xs);
  font-weight: 700;
  letter-spacing: 0.06em;
  text-transform: uppercase;
  color: var(--accent-700);
}

.dcard-title {
  display: flex;
  align-items: baseline;
  gap: 8px;
  flex: 1;
  min-width: 0;
}

.dcard-title strong {
  flex: 1;
  min-width: 0;
}

.dcard-title .num {
  flex: none;
  font-weight: 600;
  font-variant-numeric: tabular-nums;
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

.thumb {
  display: block;
  width: 100%;
  max-height: 160px;
  padding: 0;
  overflow: hidden;
  border: 1px solid var(--line);
  border-radius: var(--r-sm);
  background: var(--surface-1);
  cursor: zoom-in;
}

.thumb img {
  display: block;
  width: 100%;
  height: 160px;
  object-fit: cover;
  object-position: top;
}

.facts {
  display: grid;
  grid-template-columns: 96px minmax(0, 1fr);
  gap: 3px 10px;
  margin: 0;
}

.facts dt {
  color: var(--ink-500);
}

.facts dd {
  margin: 0;
  min-width: 0;
  overflow-wrap: anywhere;
}

.links {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
  padding-top: 4px;
  border-top: 1px solid var(--line);
}
</style>
