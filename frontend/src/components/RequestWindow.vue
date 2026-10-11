<script setup lang="ts">
/**
 * A request in a window over its list: what was asked, the conversation, and —
 * for the office — what to do with it. Like the register's window, the list
 * stays behind it, and J/K step through the requests as they were listed.
 */
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useMutation, useQuery, useQueryClient } from '@tanstack/vue-query'

import { api, ApiError } from '../api/client'
import type { RequestDetail, RequestStatus } from '../api/types'
import { formatAmount, formatDate } from '../document-fields'
import { useAuth } from '../composables/useAuth'
import { KIND_ICON, KIND_LABEL, STATUS_META } from '../requests'
import AppIcon from './AppIcon.vue'
import RequestStatusPill from './RequestStatusPill.vue'
import RoleBadge from './RoleBadge.vue'
import StatusPill from './StatusPill.vue'

const props = defineProps<{ id: number; queue: number[] }>()
const emit = defineEmits<{ open: [id: number]; close: [] }>()

const auth = useAuth()
const queryClient = useQueryClient()
const panel = ref<HTMLElement | null>(null)
const thread = ref<HTMLElement | null>(null)

const detailQuery = useQuery({
  queryKey: computed(() => ['request', props.id]),
  queryFn: () => api.getRequest(props.id),
  // A conversation should not wait for a focus change to show a reply.
  refetchInterval: 20_000,
})
const request = computed(() => detailQuery.data.value)

/** The office, to hand a request to. */
const officeQuery = useQuery({
  queryKey: ['requests', 'office'],
  queryFn: api.requestOffice,
  enabled: auth.isStaff,
  staleTime: 5 * 60_000,
})
const office = computed(() => officeQuery.data.value ?? [])

const position = computed(() => props.queue.indexOf(props.id))
const previous = computed(() => (position.value > 0 ? props.queue[position.value - 1] : undefined))
const next = computed(() =>
  position.value >= 0 && position.value < props.queue.length - 1 ? props.queue[position.value + 1] : undefined,
)

const reply = ref('')
const error = ref('')
/** A move waiting for its note: refusing always needs one, others may have one. */
const pendingMove = ref<RequestStatus | null>(null)
const moveNote = ref('')

function dirty() {
  return reply.value.trim() !== '' || moveNote.value.trim() !== ''
}
function mayLeave() {
  return !dirty() || window.confirm('Hi ha un missatge sense enviar. Vols descartar-lo?')
}
function go(id: number | undefined) {
  if (id !== undefined && mayLeave()) emit('open', id)
}
function close() {
  if (mayLeave()) emit('close')
}

function settled(updated: RequestDetail) {
  queryClient.setQueryData(['request', updated.id], updated)
  void queryClient.invalidateQueries({ queryKey: ['requests'] })
  void queryClient.invalidateQueries({ queryKey: ['notifications'] })
  error.value = ''
}
function failed(err: unknown) {
  error.value = err instanceof ApiError ? err.message : "No s'ha pogut desar."
}

const send = useMutation({
  mutationFn: () => api.replyToRequest(props.id, reply.value),
  onSuccess: (updated) => {
    reply.value = ''
    settled(updated)
  },
  onError: failed,
})

const move = useMutation({
  mutationFn: (input: { status: RequestStatus; note: string }) =>
    api.moveRequest(props.id, input.status, input.note),
  onSuccess: (updated) => {
    pendingMove.value = null
    moveNote.value = ''
    settled(updated)
  },
  onError: failed,
})

const assign = useMutation({
  mutationFn: (assigneeId: number | null) => api.assignRequest(props.id, assigneeId),
  onSuccess: settled,
  onError: failed,
})

function startMove(status: RequestStatus) {
  error.value = ''
  // Withdrawing and reopening say enough on their own.
  if (status === 'cancellada' || status === 'en_revisio' || status === 'oberta') {
    move.mutate({ status, note: '' })
    return
  }
  pendingMove.value = status
  moveNote.value = ''
}

function confirmMove() {
  if (!pendingMove.value) return
  if (pendingMove.value === 'rebutjada' && !moveNote.value.trim()) return
  move.mutate({ status: pendingMove.value, note: moveNote.value })
}

const isOffice = computed(() => auth.isStaff.value)
const isMine = computed(() => request.value?.requester.id === auth.user.value?.id)
const movesForMe = computed(() => request.value?.allowed_statuses ?? [])

const NOTE_PROMPT: Partial<Record<RequestStatus, string>> = {
  aprovada: 'Afegeix-hi una nota si cal (opcional): com es farà, qui ho compra…',
  rebutjada: 'Per què es rebutja? Ho veurà la persona que ho ha demanat.',
  resolta: 'Com ha quedat (opcional).',
}

function when(iso: string) {
  return new Date(iso).toLocaleString('ca-ES', {
    day: 'numeric',
    month: 'short',
    hour: '2-digit',
    minute: '2-digit',
  })
}

// Newest at the bottom, like any conversation: open scrolled to it.
watch(
  () => request.value?.messages.length,
  () => void nextTick(() => thread.value?.scrollTo({ top: thread.value.scrollHeight })),
)
watch(
  () => props.id,
  () => {
    reply.value = ''
    pendingMove.value = null
    error.value = ''
  },
)

function inField(target: EventTarget | null) {
  return target instanceof HTMLElement && Boolean(target.closest('input, textarea, select'))
}
function onKey(event: KeyboardEvent) {
  if (event.key === 'Escape') {
    if (inField(event.target)) (event.target as HTMLElement).blur()
    else close()
    return
  }
  if (inField(event.target) || event.metaKey || event.ctrlKey || event.altKey) return
  if (event.key === 'j' || event.key === 'ArrowRight') go(next.value)
  else if (event.key === 'k' || event.key === 'ArrowLeft') go(previous.value)
}
function onReplyKey(event: KeyboardEvent) {
  if (event.key === 'Enter' && (event.metaKey || event.ctrlKey) && reply.value.trim()) send.mutate()
}

let restoreOverflow = ''
onMounted(() => {
  restoreOverflow = document.documentElement.style.overflow
  document.documentElement.style.overflow = 'hidden'
  window.addEventListener('keydown', onKey)
  panel.value?.focus()
})
onBeforeUnmount(() => {
  document.documentElement.style.overflow = restoreOverflow
  window.removeEventListener('keydown', onKey)
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
        :aria-label="request?.title ?? 'Sol·licitud'"
        tabindex="-1"
      >
        <header class="window-head">
          <div v-if="queue.length > 1" class="nav">
            <button class="icon-btn" type="button" title="Anterior (K o ←)" :disabled="previous === undefined" @click="go(previous)">
              <AppIcon name="chevronLeft" :size="14" />
              <span class="sr-only">Anterior</span>
            </button>
            <span class="pos mono">
              <template v-if="position >= 0">{{ position + 1 }} / {{ queue.length }}</template>
              <template v-else>—</template>
            </span>
            <button class="icon-btn" type="button" title="Següent (J o →)" :disabled="next === undefined" @click="go(next)">
              <AppIcon name="chevron" :size="14" />
              <span class="sr-only">Següent</span>
            </button>
          </div>

          <div class="title">
            <strong class="truncate">{{ request?.title ?? 'Carregant…' }}</strong>
            <span v-if="request" class="truncate">
              <span class="mono">{{ request.code }}</span> · {{ KIND_LABEL[request.kind] }} · {{ request.requester.name }}
            </span>
          </div>
          <RequestStatusPill v-if="request" :status="request.status" />
          <button class="icon-btn" type="button" title="Tanca (Esc)" @click="close">
            <AppIcon name="close" :size="15" />
            <span class="sr-only">Tanca</span>
          </button>
        </header>

        <p v-if="detailQuery.isError.value" class="window-empty">
          <span class="notice notice-error">
            <AppIcon name="alert" :size="15" />
            <span>{{ (detailQuery.error.value as Error).message }}</span>
          </span>
        </p>

        <div v-else-if="request" class="window-body">
          <!-- ── The conversation ───────────────────────────────────── -->
          <div class="conversation">
            <div ref="thread" class="thread">
              <article class="ask">
                <header class="ask-head">
                  <span class="kind-chip">
                    <AppIcon :name="KIND_ICON[request.kind]" :size="13" />
                    {{ KIND_LABEL[request.kind] }}
                  </span>
                  <span class="muted">{{ when(request.created_at) }}</span>
                </header>
                <h2 class="ask-title">{{ request.title }}</h2>
                <p v-if="request.description" class="ask-body">{{ request.description }}</p>
                <dl v-if="request.kind !== 'consulta'" class="facts">
                  <div>
                    <dt>Import</dt>
                    <dd class="mono">{{ request.amount != null ? formatAmount(request.amount) : '—' }}</dd>
                  </div>
                  <div>
                    <dt>Proveïdor</dt>
                    <dd>{{ request.proveidor || '—' }}</dd>
                  </div>
                  <div>
                    <dt>Compte</dt>
                    <dd>{{ request.compte || '—' }}</dd>
                  </div>
                  <div>
                    <dt>{{ request.kind === 'reemborsament' ? 'Data de compra' : 'Per quan' }}</dt>
                    <dd class="mono">{{ formatDate(request.needed_by) || '—' }}</dd>
                  </div>
                </dl>
              </article>

              <template v-for="entry in request.messages" :key="entry.id">
                <p v-if="entry.kind === 'status'" class="event">
                  <span class="event-line" aria-hidden="true" />
                  <span>
                    <strong>{{ entry.author?.name ?? 'Cosecre' }}</strong>
                    l'ha marcada com a
                    <RequestStatusPill v-if="entry.status" :status="entry.status" />
                    <span class="muted"> · {{ when(entry.created_at) }}</span>
                  </span>
                  <span v-if="entry.body" class="event-note">{{ entry.body }}</span>
                </p>
                <article
                  v-else
                  class="message"
                  :class="{ mine: entry.author?.id === auth.user.value?.id, office: entry.author?.role !== 'professor' }"
                >
                  <header class="message-head">
                    <strong>{{ entry.author?.name ?? 'Compte eliminat' }}</strong>
                    <RoleBadge v-if="entry.author" :role="entry.author.role" />
                    <span class="muted">{{ when(entry.created_at) }}</span>
                  </header>
                  <p class="message-body">{{ entry.body }}</p>
                </article>
              </template>
            </div>

            <form v-if="request.can_reply" class="composer" @submit.prevent="send.mutate()">
              <textarea
                v-model="reply"
                class="textarea"
                rows="2"
                :placeholder="isOffice && !isMine ? `Respon a ${request.requester.name}…` : 'Escriu a secretaria…'"
                aria-label="Missatge"
                @keydown="onReplyKey"
              />
              <button class="btn btn-primary" type="submit" :disabled="!reply.trim() || send.isPending.value" title="Envia (⌘↵)">
                <AppIcon name="send" :size="14" />
                Envia
              </button>
            </form>
            <p v-else class="closed muted">Aquesta sol·licitud està cancel·lada.</p>
          </div>

          <!-- ── What to do with it ─────────────────────────────────── -->
          <aside class="side">
            <section v-if="movesForMe.length" class="side-block">
              <h3 class="side-title">{{ isOffice ? 'Decideix' : 'Accions' }}</h3>
              <div v-if="!pendingMove" class="moves">
                <button
                  v-for="status in movesForMe"
                  :key="status"
                  class="btn btn-sm btn-block"
                  :class="status === 'aprovada' ? 'btn-primary' : status === 'rebutjada' || status === 'cancellada' ? 'btn-outline danger' : 'btn-outline'"
                  type="button"
                  :disabled="move.isPending.value"
                  @click="startMove(status)"
                >
                  {{ STATUS_META[status].verb }}
                </button>
              </div>
              <form v-else class="move-note" @submit.prevent="confirmMove">
                <span class="label">{{ STATUS_META[pendingMove].verb }}</span>
                <textarea
                  v-model="moveNote"
                  class="textarea"
                  rows="3"
                  :placeholder="NOTE_PROMPT[pendingMove]"
                  :required="pendingMove === 'rebutjada'"
                />
                <div class="move-actions">
                  <button class="btn btn-ghost btn-sm" type="button" @click="pendingMove = null">Enrere</button>
                  <button
                    class="btn btn-sm"
                    :class="pendingMove === 'rebutjada' ? 'btn-danger' : 'btn-primary'"
                    type="submit"
                    :disabled="move.isPending.value || (pendingMove === 'rebutjada' && !moveNote.trim())"
                  >
                    {{ STATUS_META[pendingMove].verb }}
                  </button>
                </div>
              </form>
            </section>

            <section v-if="isOffice" class="side-block">
              <h3 class="side-title">Se n'encarrega</h3>
              <select
                class="select"
                :value="request.assignee?.id ?? ''"
                :disabled="assign.isPending.value"
                aria-label="Qui se n'encarrega"
                @change="
                  assign.mutate(
                    ($event.target as HTMLSelectElement).value
                      ? Number(($event.target as HTMLSelectElement).value)
                      : null,
                  )
                "
              >
                <option value="">Ningú encara</option>
                <option v-for="person in office" :key="person.id" :value="person.id">{{ person.name }}</option>
              </select>
            </section>
            <section v-else-if="request.assignee" class="side-block">
              <h3 class="side-title">Se n'encarrega</h3>
              <p class="person">{{ request.assignee.name }}</p>
            </section>

            <section class="side-block">
              <h3 class="side-title">Documents</h3>
              <ul v-if="request.documents.length" class="docs">
                <li v-for="doc in request.documents" :key="doc.num_doc_intern" class="doc">
                  <span class="truncate">
                    <strong>{{ doc.num_factura || 'Sense número' }}</strong>
                    <span class="muted"> · {{ doc.proveidor || 'Proveïdor per llegir' }}</span>
                  </span>
                  <span class="doc-meta">
                    <span class="mono">{{ formatAmount(doc.import_value) }}</span>
                    <StatusPill :status="doc.status" />
                  </span>
                </li>
              </ul>
              <p v-else class="muted small">Cap factura ni tiquet adjunt.</p>
            </section>

            <p v-if="error" class="notice notice-error">
              <AppIcon name="alert" :size="15" />
              <span>{{ error }}</span>
            </p>
          </aside>
        </div>

        <p v-else class="window-empty muted">Carregant…</p>
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
  background: rgb(27 44 70 / 0.32);
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
  width: min(980px, 100%);
  height: min(760px, 100%);
  background: var(--surface-1);
  border: 1px solid var(--line);
  border-radius: var(--r-xl);
  box-shadow: var(--shadow-lg);
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
  color: var(--ink-900);
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
  color: var(--ink-900);
}

.icon-btn:disabled {
  opacity: 0.35;
  cursor: default;
}

.window-empty {
  padding: 24px;
}

.window-body {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 248px;
  min-height: 0;
}

/* ── Conversation ─────────────────────────────────────────────────────── */
.conversation {
  display: grid;
  grid-template-rows: minmax(0, 1fr) auto;
  min-height: 0;
  border-right: 1px solid var(--line);
}

.thread {
  display: flex;
  flex-direction: column;
  gap: 10px;
  padding: 14px;
  overflow: auto;
  overscroll-behavior: contain;
}

.ask {
  display: grid;
  gap: 8px;
  padding: 12px 14px;
  border: 1px solid var(--line);
  border-radius: var(--r-lg);
  background: var(--surface-0);
}

.ask-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  font-size: var(--text-sm);
}

.kind-chip {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  font-size: var(--text-xs);
  font-weight: 600;
  letter-spacing: 0.04em;
  text-transform: uppercase;
  color: var(--accent-700);
}

.ask-title {
  font-size: var(--text-md);
}

.ask-body,
.message-body {
  white-space: pre-wrap;
  font-size: var(--text-base);
  line-height: 1.55;
  color: var(--ink-700);
}

.facts {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 8px;
  margin: 2px 0 0;
  padding-top: 10px;
  border-top: 1px solid var(--line);
}

.facts dt {
  font-size: var(--text-xs);
  font-weight: 600;
  letter-spacing: 0.06em;
  text-transform: uppercase;
  color: var(--ink-400);
}

.facts dd {
  margin: 2px 0 0;
  font-size: var(--text-base);
  color: var(--ink-900);
}

.message {
  display: grid;
  gap: 4px;
  max-width: 85%;
  padding: 9px 12px;
  border: 1px solid var(--line);
  border-radius: var(--r-lg);
  background: var(--surface-0);
}

.message.office {
  border-color: var(--accent-200);
  background: var(--accent-50);
}

.message.mine {
  align-self: flex-end;
}

.message-head {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 6px;
  font-size: var(--text-sm);
}

.event {
  display: grid;
  gap: 4px;
  justify-items: center;
  margin: 2px 0;
  font-size: var(--text-sm);
  color: var(--ink-500);
  text-align: center;
}

.event-note {
  max-width: 80%;
  padding: 6px 10px;
  border-radius: var(--r-md);
  background: var(--surface-2);
  white-space: pre-wrap;
  color: var(--ink-700);
}

.event-line {
  display: none;
}

.composer {
  display: flex;
  align-items: flex-end;
  gap: 8px;
  padding: 10px 14px;
  border-top: 1px solid var(--line);
  background: var(--surface-0);
}

.composer .textarea {
  flex: 1;
  resize: vertical;
  min-height: 40px;
}

.closed {
  padding: 12px 14px;
  border-top: 1px solid var(--line);
  font-size: var(--text-sm);
}

/* ── Side ─────────────────────────────────────────────────────────────── */
.side {
  display: flex;
  flex-direction: column;
  gap: 16px;
  padding: 14px;
  overflow: auto;
}

.side-block {
  display: grid;
  gap: 7px;
}

.side-title {
  font-size: var(--text-xs);
  font-weight: 600;
  letter-spacing: 0.06em;
  text-transform: uppercase;
  color: var(--ink-400);
}

.moves {
  display: grid;
  gap: 6px;
}

.danger {
  color: var(--danger-700);
}

.move-note {
  display: grid;
  gap: 7px;
}

.move-actions {
  display: flex;
  justify-content: flex-end;
  gap: 6px;
}

.person {
  font-size: var(--text-base);
}

.docs {
  display: grid;
  gap: 6px;
  margin: 0;
  padding: 0;
  list-style: none;
}

.doc {
  display: grid;
  gap: 4px;
  padding: 7px 9px;
  border: 1px solid var(--line);
  border-radius: var(--r-md);
  background: var(--surface-0);
  font-size: var(--text-sm);
}

.doc-meta {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 6px;
}

.small {
  font-size: var(--text-sm);
}

@media (max-width: 760px) {
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
    grid-template-columns: minmax(0, 1fr);
    grid-template-rows: auto minmax(0, 1fr);
    overflow: auto;
  }

  .side {
    order: -1;
    padding-bottom: 0;
    overflow: visible;
  }

  .conversation {
    border-right: 0;
  }

  .facts {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}
</style>
