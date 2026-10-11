<script setup lang="ts">
/**
 * The bell, and the list it opens. The count is polled — the hub has no push
 * channel, and half a minute is soon enough for requests to the office — and
 * re-read whenever the window comes back into focus.
 *
 * The list floats over the page, anchored to the bell, rather than taking a
 * column of its own.
 */
import { computed, nextTick, onBeforeUnmount, ref } from 'vue'
import { useMutation, useQuery, useQueryClient } from '@tanstack/vue-query'
import { useRouter } from 'vue-router'

import { api } from '../api/client'
import type { AppNotification } from '../api/types'
import AppIcon from './AppIcon.vue'

const router = useRouter()
const queryClient = useQueryClient()

const open = ref(false)
const button = ref<HTMLElement | null>(null)
const panel = ref<HTMLElement | null>(null)
const position = ref({ top: 0, left: 0 })

const countQuery = useQuery({
  queryKey: ['notifications', 'count'],
  queryFn: api.unreadNotifications,
  refetchInterval: 30_000,
})
const unread = computed(() => countQuery.data.value?.count ?? 0)

const listQuery = useQuery({
  queryKey: ['notifications', 'list'],
  queryFn: () => api.notifications(30),
  enabled: open,
})
const items = computed(() => listQuery.data.value ?? [])

function refresh() {
  void queryClient.invalidateQueries({ queryKey: ['notifications'] })
}

const readOne = useMutation({ mutationFn: (id: number) => api.readNotification(id), onSuccess: refresh })
const readAll = useMutation({ mutationFn: api.readAllNotifications, onSuccess: refresh })

const PANEL_W = 340

function place() {
  const rect = button.value?.getBoundingClientRect()
  if (!rect) return
  const left = Math.min(Math.max(8, rect.left), window.innerWidth - PANEL_W - 8)
  position.value = { top: rect.bottom + 6, left }
}

async function toggle() {
  open.value = !open.value
  if (!open.value) return
  place()
  // A new notification may have arrived since the count was last read.
  refresh()
  await nextTick()
  panel.value?.focus()
}

function close() {
  open.value = false
}

function onPointer(event: PointerEvent) {
  const target = event.target as Node
  if (!panel.value?.contains(target) && !button.value?.contains(target)) close()
}
function onKey(event: KeyboardEvent) {
  if (event.key === 'Escape' && open.value) {
    close()
    button.value?.focus()
  }
}
window.addEventListener('pointerdown', onPointer, true)
window.addEventListener('keydown', onKey)
window.addEventListener('resize', close)
onBeforeUnmount(() => {
  window.removeEventListener('pointerdown', onPointer, true)
  window.removeEventListener('keydown', onKey)
  window.removeEventListener('resize', close)
})

async function follow(item: AppNotification) {
  if (!item.read) readOne.mutate(item.id)
  close()
  if (item.link) await router.push(item.link)
}

function ago(iso: string) {
  const minutes = Math.round((Date.now() - new Date(iso).getTime()) / 60_000)
  if (minutes < 1) return 'ara'
  if (minutes < 60) return `fa ${minutes} min`
  const hours = Math.round(minutes / 60)
  if (hours < 24) return `fa ${hours} h`
  const days = Math.round(hours / 24)
  if (days < 7) return `fa ${days} d`
  return new Date(iso).toLocaleDateString('ca-ES', { day: 'numeric', month: 'short' })
}

const label = computed(() =>
  unread.value ? `Notificacions: ${unread.value} sense llegir` : 'Notificacions',
)
</script>

<template>
  <button
    ref="button"
    class="btn btn-ghost btn-icon bell"
    :class="{ on: open }"
    type="button"
    :title="label"
    :aria-label="label"
    :aria-expanded="open"
    aria-haspopup="dialog"
    @click="toggle"
  >
    <AppIcon name="bell" />
    <span v-if="unread" class="count" aria-hidden="true">{{ unread > 99 ? '99+' : unread }}</span>
  </button>

  <Teleport to="body">
    <section
      v-if="open"
      ref="panel"
      class="panel"
      role="dialog"
      aria-label="Notificacions"
      tabindex="-1"
      :style="{ top: `${position.top}px`, left: `${position.left}px`, width: `${PANEL_W}px` }"
    >
      <header class="head">
        <strong>Notificacions</strong>
        <button
          v-if="unread"
          class="btn btn-ghost btn-sm"
          type="button"
          :disabled="readAll.isPending.value"
          @click="readAll.mutate()"
        >
          Marca-ho tot com a llegit
        </button>
      </header>

      <p v-if="listQuery.isLoading.value" class="empty">Carregant…</p>
      <div v-else-if="!items.length" class="empty-state">
        <AppIcon name="inbox" :size="20" />
        <span>No tens cap notificació.</span>
      </div>
      <ul v-else class="list">
        <li v-for="item in items" :key="item.id">
          <button class="item" :class="{ unread: !item.read }" type="button" @click="follow(item)">
            <span class="dot" aria-hidden="true" />
            <span class="text">
              <span class="title">{{ item.title }}</span>
              <span v-if="item.body" class="body">{{ item.body }}</span>
              <span class="when">{{ ago(item.created_at) }}</span>
            </span>
          </button>
        </li>
      </ul>
    </section>
  </Teleport>
</template>

<style scoped>
.bell {
  position: relative;
}

.bell.on {
  background: var(--surface-2);
  color: var(--ink-900);
}

.count {
  position: absolute;
  top: 2px;
  right: 1px;
  box-sizing: border-box;
  min-width: 15px;
  height: 15px;
  padding: 0 3px;
  border: 2px solid var(--surface-0);
  border-radius: var(--r-full);
  background: var(--danger-600);
  color: #fff;
  font-size: 9px;
  font-weight: 700;
  line-height: 11px;
  text-align: center;
  font-variant-numeric: tabular-nums;
  pointer-events: none;
}

.panel {
  position: fixed;
  z-index: 90;
  display: grid;
  grid-template-rows: auto minmax(0, 1fr);
  max-height: min(520px, calc(100vh - 80px));
  max-width: calc(100vw - 16px);
  background: var(--surface-0);
  border: 1px solid var(--line);
  border-radius: var(--r-lg);
  box-shadow: var(--shadow-lg);
  outline: none;
  overflow: hidden;
  animation: drop 0.12s ease-out;
}

@keyframes drop {
  from {
    opacity: 0;
    transform: translateY(-4px);
  }
}

.head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  min-height: 40px;
  padding: 6px 8px 6px 12px;
  border-bottom: 1px solid var(--line);
  font-size: var(--text-base);
}

.list {
  margin: 0;
  padding: 4px;
  list-style: none;
  overflow: auto;
  overscroll-behavior: contain;
}

.item {
  display: flex;
  align-items: flex-start;
  gap: 8px;
  width: 100%;
  padding: 8px;
  border: 0;
  border-radius: var(--r-md);
  background: none;
  text-align: left;
  font: inherit;
  color: inherit;
  cursor: pointer;
}

.item:hover,
.item:focus-visible {
  background: var(--surface-2);
  outline: none;
}

.dot {
  flex: none;
  width: 7px;
  height: 7px;
  margin-top: 6px;
  border-radius: var(--r-full);
  background: transparent;
}

.item.unread .dot {
  background: var(--accent-600);
}

.text {
  display: grid;
  gap: 2px;
  min-width: 0;
}

.title {
  font-size: var(--text-base);
  line-height: 1.35;
  color: var(--ink-700);
}

.item.unread .title {
  font-weight: 600;
  color: var(--ink-900);
}

.body {
  overflow: hidden;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  font-size: var(--text-sm);
  line-height: 1.4;
  color: var(--ink-500);
}

.when {
  font-size: var(--text-xs);
  color: var(--ink-400);
}

.empty,
.empty-state {
  padding: 28px 16px;
  font-size: var(--text-base);
  text-align: center;
  color: var(--ink-400);
}

.empty-state {
  display: grid;
  justify-items: center;
  gap: 8px;
}
</style>
