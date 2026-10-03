<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { RouterLink } from 'vue-router'

import type { DocumentRecord } from '../api/types'
import { formatAmount, formatDate } from '../document-fields'
import AppIcon from './AppIcon.vue'
import DocumentEditor from './DocumentEditor.vue'
import StatusPill from './StatusPill.vue'

/**
 * A register entry in a window over the list, so checking one does not lose
 * your place in it. The list behind is dimmed, not gone: closing returns to
 * the same filter, search and scroll.
 *
 * `queue` is the list as it was when the window opened. It stays put while
 * you work through it, so validating an entry under "Per revisar" does not
 * pull the next one out from under "Següent".
 */
const props = defineProps<{
  id: string
  queue: string[]
  documents: DocumentRecord[]
}>()
const emit = defineEmits<{ open: [id: string]; close: [] }>()

const editor = ref<InstanceType<typeof DocumentEditor> | null>(null)
const body = ref<HTMLElement | null>(null)
const panel = ref<HTMLElement | null>(null)

const record = computed(() => props.documents.find((item) => item.num_doc_intern === props.id))

/** Entries deleted since the window opened are skipped, not shown as blanks. */
const live = computed(() => {
  const known = new Set(props.documents.map((item) => item.num_doc_intern))
  return props.queue.filter((id) => id === props.id || known.has(id))
})
const position = computed(() => live.value.indexOf(props.id))
const previous = computed(() => (position.value > 0 ? live.value[position.value - 1] : undefined))
const next = computed(() =>
  position.value >= 0 && position.value < live.value.length - 1 ? live.value[position.value + 1] : undefined,
)

function mayLeave() {
  return !editor.value?.dirty || window.confirm('Hi ha canvis sense desar. Vols descartar-los?')
}

function go(id: string | undefined) {
  if (id && mayLeave()) emit('open', id)
}

function close() {
  if (mayLeave()) emit('close')
}

/** A validation sends the window on only when asked to, and to the entry that was next when asked. */
function onValidated(advance: boolean) {
  if (advance && next.value) emit('open', next.value)
}

// A new entry starts at its top, with the keyboard inside the window.
watch(
  () => props.id,
  () => {
    void nextTick(() => body.value?.scrollTo({ top: 0 }))
  },
)

function inField(target: EventTarget | null) {
  return target instanceof HTMLElement && Boolean(target.closest('input, textarea, select, [contenteditable]'))
}

function onKey(event: KeyboardEvent) {
  // The original's own full-screen viewer closes first.
  if (editor.value?.viewerOpen) return
  if (event.key === 'Escape') {
    // Out of a field first, out of the window second: Esc in a half-typed
    // field should not throw the whole entry away.
    if (inField(event.target)) (event.target as HTMLElement).blur()
    else close()
    return
  }
  if (inField(event.target) || event.metaKey || event.ctrlKey || event.altKey) return
  if (event.key === 'j' || event.key === 'ArrowRight') {
    event.preventDefault()
    go(next.value)
  } else if (event.key === 'k' || event.key === 'ArrowLeft') {
    event.preventDefault()
    go(previous.value)
  }
}

let restoreFocus: HTMLElement | null = null
let restoreOverflow = ''

onMounted(() => {
  restoreFocus = document.activeElement as HTMLElement | null
  // The page behind should not scroll under the window.
  restoreOverflow = document.documentElement.style.overflow
  document.documentElement.style.overflow = 'hidden'
  window.addEventListener('keydown', onKey)
  panel.value?.focus()
})

onBeforeUnmount(() => {
  document.documentElement.style.overflow = restoreOverflow
  window.removeEventListener('keydown', onKey)
  restoreFocus?.focus?.()
})
</script>

<template>
  <Teleport to="body">
    <div class="scrim" @mousedown.self="close">
      <section
        ref="panel"
        class="window"
        role="dialog"
        aria-modal="true"
        :aria-label="record?.num_factura || id"
        tabindex="-1"
      >
        <header class="window-head">
          <div class="nav">
            <button
              class="icon-btn"
              type="button"
              title="Anterior (K o ←)"
              :disabled="!previous"
              @click="go(previous)"
            >
              <AppIcon name="chevron" :size="14" class="flip" />
              <span class="sr-only">Anterior</span>
            </button>
            <span class="pos mono">
              <template v-if="position >= 0">{{ position + 1 }} / {{ live.length }}</template>
              <template v-else>—</template>
            </span>
            <button
              class="icon-btn"
              type="button"
              title="Següent (J o →)"
              :disabled="!next"
              @click="go(next)"
            >
              <AppIcon name="chevron" :size="14" />
              <span class="sr-only">Següent</span>
            </button>
          </div>

          <div class="title">
            <strong class="truncate">
              {{ record?.num_factura || 'Sense número' }}
              <span class="ref mono">{{ id }}</span>
            </strong>
            <span class="truncate">
              {{ record?.proveidor || 'Proveïdor desconegut' }}
              <template v-if="record?.tipus_document"> · {{ record.tipus_document }}</template>
              <template v-if="record?.data_factura"> · {{ formatDate(record.data_factura) }}</template>
              <template v-if="record?.import != null">
                · <span class="amount">{{ formatAmount(record.import) }}</span>
              </template>
            </span>
          </div>

          <StatusPill v-if="record" :status="record.extraction_status" />

          <RouterLink
            class="icon-btn"
            :to="{ name: 'document', params: { internalDocNumber: id } }"
            title="Obre a pàgina completa"
          >
            <AppIcon name="external" :size="14" />
            <span class="sr-only">Obre a pàgina completa</span>
          </RouterLink>
          <button class="icon-btn" type="button" title="Tanca (Esc)" @click="close">
            <AppIcon name="close" :size="15" />
            <span class="sr-only">Tanca</span>
          </button>
        </header>

        <div ref="body" class="window-body">
          <DocumentEditor
            ref="editor"
            :key="id"
            :internal-doc-number="id"
            embedded
            :has-next="Boolean(next)"
            @validated="onValidated"
          />
        </div>
      </section>
    </div>
  </Teleport>
</template>

<style scoped>
.scrim {
  position: fixed;
  inset: 0;
  z-index: 70;
  display: grid;
  place-items: center;
  padding: 20px;
  background: rgb(28 25 23 / 0.38);
  backdrop-filter: blur(1.5px);
  -webkit-backdrop-filter: blur(1.5px);
  animation: fade 0.14s ease-out;
}

@keyframes fade {
  from {
    opacity: 0;
  }
}

.window {
  display: grid;
  grid-template-rows: auto minmax(0, 1fr);
  width: min(1240px, 100%);
  height: min(920px, 100%);
  background: var(--surface-1);
  border: 1px solid var(--line);
  border-radius: var(--r-xl);
  box-shadow:
    0 1px 2px rgb(28 25 23 / 0.06),
    0 24px 60px -12px rgb(28 25 23 / 0.35);
  overflow: hidden;
  outline: none;
  animation: rise 0.16s ease-out;
}

@keyframes rise {
  from {
    opacity: 0;
    transform: translateY(8px) scale(0.99);
  }
}

.window-head {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 8px 10px;
  border-bottom: 1px solid var(--line);
  background: var(--surface-0);
}

.nav {
  display: inline-flex;
  align-items: center;
  flex: none;
  padding: 2px;
  border: 1px solid var(--line);
  border-radius: var(--r-md);
}

.pos {
  min-width: 52px;
  font-size: var(--text-xs);
  text-align: center;
  color: var(--ink-500);
  font-variant-numeric: tabular-nums;
}

.flip {
  transform: rotate(180deg);
}

.title {
  display: grid;
  flex: 1;
  min-width: 0;
  line-height: 1.3;
  font-size: var(--text-sm);
  color: var(--ink-500);
}

.title strong {
  font-size: var(--text-base);
  color: var(--ink-900, var(--ink-700));
}

.title .ref {
  margin-left: 6px;
  font-size: var(--text-xs);
  font-weight: 400;
  color: var(--ink-400);
}

.amount {
  font-variant-numeric: tabular-nums;
  color: var(--ink-700);
}

.icon-btn {
  display: inline-grid;
  place-items: center;
  flex: none;
  width: 28px;
  height: 28px;
  border: 0;
  border-radius: var(--r-sm);
  background: transparent;
  color: var(--ink-500);
  cursor: pointer;
}

.icon-btn:hover:not(:disabled) {
  background: var(--surface-2);
  color: var(--ink-900, var(--ink-700));
}

.icon-btn:disabled {
  opacity: 0.35;
  cursor: default;
}

.window-body {
  overflow: auto;
  overscroll-behavior: contain;
  padding: 14px;
}

@media (max-width: 640px) {
  .scrim {
    padding: 0;
  }

  .window {
    width: 100%;
    height: 100%;
    border: 0;
    border-radius: 0;
  }

  .window-body {
    padding: 10px;
  }

  .title .ref {
    display: none;
  }
}
</style>
