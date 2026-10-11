<script setup lang="ts">
import { useQuery, useQueryClient } from '@tanstack/vue-query'
import { computed, nextTick, onBeforeUnmount, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import { api, ApiError } from '../api/client'
import type {
  AssistantBlock,
  AssistantConversationSummary,
  AssistantFrame,
  AssistantMessage,
  AssistantProposal,
} from '../api/types'
import AppIcon from '../components/AppIcon.vue'
import AssistantMessageView from '../components/assistant/AssistantMessageView.vue'

/**
 * Assistent (beta): a chat with the hub's data.
 *
 * Each person's chats are their own, kept on the hub until they delete them.
 * The open chat lives in the query (`?c=12`) so a reload or a link lands on it.
 */
const route = useRoute()
const router = useRouter()
const queryClient = useQueryClient()

const statusQuery = useQuery({ queryKey: ['assistant', 'status'], queryFn: api.assistantStatus })
const listQuery = useQuery({ queryKey: ['assistant', 'conversations'], queryFn: api.assistantConversations })
const conversations = computed<AssistantConversationSummary[]>(() => listQuery.data.value ?? [])

const activeId = computed(() => {
  const raw = Number(route.query.c)
  return Number.isFinite(raw) && raw > 0 ? raw : null
})

const messages = ref<AssistantMessage[]>([])
const title = ref('')
const loading = ref(false)
const loadError = ref('')
const draft = ref('')
const sending = ref(false)
const working = ref('')
const sendError = ref('')
const confirmDelete = ref<number | null>(null)
const editingTitle = ref(false)
const titleDraft = ref('')
let abort: AbortController | null = null
/** A chat `send` just created: already on screen, so the watcher must not reload it. */
let fresh: number | null = null

const scroller = ref<HTMLElement | null>(null)
const composer = ref<HTMLTextAreaElement | null>(null)

const EXAMPLES = [
  'Quant hem gastat per compte aquest curs? Fes-ne un gràfic per mesos.',
  'Quins són els 10 proveïdors que més ens han facturat enguany?',
  'Quines factures pagades no tenen cap moviment bancari que les justifiqui?',
  'Quins documents porten més d’una setmana pendents de validar?',
]

async function load(id: number | null) {
  abort?.abort()
  messages.value = []
  title.value = ''
  loadError.value = ''
  editingTitle.value = false
  if (id == null) return
  loading.value = true
  try {
    const conversation = await api.assistantConversation(id)
    if (activeId.value !== id) return
    messages.value = conversation.messages
    title.value = conversation.title
    await scrollToEnd()
  } catch (caught) {
    loadError.value = caught instanceof ApiError ? caught.message : "No s'ha pogut obrir la conversa."
  } finally {
    loading.value = false
  }
}

watch(
  activeId,
  (id) => {
    if (id != null && id === fresh) {
      fresh = null
      return
    }
    void load(id)
  },
  { immediate: true },
)

function open(id: number | null) {
  void router.replace({ query: { ...route.query, c: id ?? undefined } })
}

async function scrollToEnd(force = true) {
  await nextTick()
  const el = scroller.value
  if (!el) return
  const nearEnd = el.scrollHeight - el.scrollTop - el.clientHeight < 160
  if (force || nearEnd) el.scrollTop = el.scrollHeight
}

// ── Asking ───────────────────────────────────────────────────────────────────

function lastText(message: AssistantMessage): Extract<AssistantBlock, { type: 'text' }> {
  const last = message.blocks[message.blocks.length - 1]
  if (last?.type === 'text') return last
  const block: Extract<AssistantBlock, { type: 'text' }> = { type: 'text', text: '' }
  message.blocks.push(block)
  return block
}

async function send(text = draft.value) {
  const question = text.trim()
  if (!question || sending.value) return
  sendError.value = ''
  sending.value = true
  working.value = 'Pensant…'
  let id = activeId.value
  try {
    if (id == null) {
      const created = await api.createAssistantConversation()
      id = created.id
      fresh = id
      await router.replace({ query: { ...route.query, c: id } })
    }
    draft.value = ''
    const live = ref<AssistantMessage | null>(null)
    abort = new AbortController()
    await api.askAssistant(
      id,
      question,
      (frame: AssistantFrame) => {
        if (frame.type === 'user') {
          messages.value.push(frame.message)
          live.value = {
            id: -1,
            role: 'assistant',
            content: '',
            blocks: [],
            status: 'done',
            detail: '',
            model: '',
            created_at: new Date().toISOString(),
          }
          messages.value.push(live.value)
        } else if (frame.type === 'status') {
          working.value = frame.text
        } else if (frame.type === 'delta' && live.value) {
          lastText(live.value).text += frame.text
          working.value = ''
        } else if (frame.type === 'block' && live.value) {
          live.value.blocks.push(frame.block)
        } else if (frame.type === 'done' || frame.type === 'error') {
          const index = messages.value.findIndex((m) => m.id === -1)
          const final = frame.message ?? (live.value ? { ...live.value, status: 'error' as const, detail: frame.type === 'error' ? frame.detail : '' } : null)
          if (final && index >= 0) messages.value.splice(index, 1, final)
          else if (frame.type === 'error') sendError.value = frame.detail
          live.value = null
        }
        void scrollToEnd(false)
      },
      abort.signal,
    )
  } catch (caught) {
    if ((caught as Error)?.name !== 'AbortError') {
      sendError.value = caught instanceof ApiError ? caught.message : "No s'ha pogut enviar."
      if (!draft.value) draft.value = question
    }
    const index = messages.value.findIndex((m) => m.id === -1)
    if (index >= 0) messages.value.splice(index, 1)
  } finally {
    sending.value = false
    working.value = ''
    abort = null
    void queryClient.invalidateQueries({ queryKey: ['assistant', 'conversations'] })
    if (id != null && !title.value) {
      title.value = conversations.value.find((c) => c.id === id)?.title ?? ''
      void api.assistantConversation(id).then((c) => {
        if (activeId.value === id) title.value = c.title
      })
    }
    await nextTick()
    composer.value?.focus()
  }
}

function stop() {
  abort?.abort()
}

function onKey(event: KeyboardEvent) {
  if (event.key === 'Enter' && !event.shiftKey && !event.isComposing) {
    event.preventDefault()
    void send()
  }
}

function proposalUpdated(proposal: AssistantProposal) {
  for (const message of messages.value) {
    for (const block of message.blocks) {
      if (block.type === 'proposal' && block.proposal_id === proposal.id) block.proposal = proposal
    }
  }
}

// ── Managing chats ───────────────────────────────────────────────────────────

async function remove(id: number) {
  if (confirmDelete.value !== id) {
    confirmDelete.value = id
    return
  }
  confirmDelete.value = null
  try {
    await api.deleteAssistantConversation(id)
    if (activeId.value === id) open(null)
  } finally {
    void queryClient.invalidateQueries({ queryKey: ['assistant', 'conversations'] })
  }
}

function startRename() {
  titleDraft.value = title.value
  editingTitle.value = true
}

async function saveRename() {
  const id = activeId.value
  const next = titleDraft.value.trim()
  editingTitle.value = false
  if (id == null || !next || next === title.value) return
  title.value = next
  await api.renameAssistantConversation(id, next)
  void queryClient.invalidateQueries({ queryKey: ['assistant', 'conversations'] })
}

const DAY = new Intl.DateTimeFormat('ca', { day: 'numeric', month: 'short' })
const TIME = new Intl.DateTimeFormat('ca', { hour: '2-digit', minute: '2-digit' })

function when(iso: string) {
  const date = new Date(iso.endsWith('Z') || /[+-]\d\d:\d\d$/.test(iso) ? iso : `${iso}Z`)
  return date.toDateString() === new Date().toDateString() ? TIME.format(date) : DAY.format(date)
}

const ready = computed(() => statusQuery.data.value?.ready ?? true)

onBeforeUnmount(() => abort?.abort())
</script>

<template>
  <div class="assistant">
    <aside class="chats">
      <button class="btn btn-outline btn-sm new" type="button" @click="open(null)">
        <AppIcon name="plus" :size="13" />
        Conversa nova
      </button>
      <ul class="chat-list">
        <li
          v-for="chat in conversations"
          :key="chat.id"
          :class="{ active: chat.id === activeId }"
          @mouseleave="confirmDelete = confirmDelete === chat.id ? null : confirmDelete"
        >
          <button class="chat" type="button" @click="open(chat.id)">
            <span class="chat-title">{{ chat.title }}</span>
            <span class="chat-when">{{ when(chat.updated_at) }}</span>
          </button>
          <button
            class="chat-delete"
            :class="{ confirm: confirmDelete === chat.id }"
            type="button"
            :title="confirmDelete === chat.id ? 'Torna a clicar per esborrar-la' : 'Esborra la conversa'"
            :aria-label="confirmDelete === chat.id ? 'Confirma: esborra la conversa' : 'Esborra la conversa'"
            @click="remove(chat.id)"
          >
            <AppIcon name="trash" :size="13" />
            <span v-if="confirmDelete === chat.id">Esborra</span>
          </button>
        </li>
      </ul>
      <p v-if="!conversations.length && !listQuery.isLoading.value" class="chats-empty">
        Encara no hi ha cap conversa. Són només teves.
      </p>
    </aside>

    <section class="chat-pane">
      <header class="chat-head">
        <div class="chat-name">
          <input
            v-if="editingTitle"
            v-model="titleDraft"
            class="input rename"
            maxlength="255"
            @keydown.enter.prevent="saveRename"
            @keydown.esc="editingTitle = false"
            @blur="saveRename"
          />
          <button v-else-if="activeId && title" class="title-button" type="button" title="Canvia el nom" @click="startRename">
            {{ title }}
          </button>
          <span v-else class="title-plain">Assistent</span>
          <span class="badge badge-ai">beta</span>
        </div>
        <span v-if="statusQuery.data.value" class="model" :title="`Raonament: ${statusQuery.data.value.reasoning_effort}`">
          {{ statusQuery.data.value.model }}
        </span>
      </header>

      <div ref="scroller" class="thread">
        <p v-if="!ready" class="notice notice-warn">{{ statusQuery.data.value?.detail }}</p>
        <p v-if="loadError" class="notice notice-error">{{ loadError }}</p>

        <div v-if="!activeId && !messages.length" class="welcome">
          <div class="welcome-mark"><AppIcon name="sparkles" :size="20" /></div>
          <h1 class="welcome-title">Pregunta-li a les dades</h1>
          <p class="welcome-lead">
            Consulta el registre, els extractes i les sol·licituds; fa càlculs, taules i gràfics. Si li
            demanes canvis, te'ls proposa amb el valor d'abans i el de després, i només s'apliquen si
            els confirmes — i es poden desfer.
          </p>
          <div class="examples">
            <button v-for="example in EXAMPLES" :key="example" class="example" type="button" :disabled="!ready" @click="send(example)">
              {{ example }}
            </button>
          </div>
        </div>

        <p v-else-if="loading" class="loading-line">Carregant…</p>

        <div class="messages">
          <AssistantMessageView
            v-for="(message, index) in messages"
            :key="message.id"
            :message="message"
            :working="sending && index === messages.length - 1 && message.id === -1 ? working : ''"
            @proposal="proposalUpdated"
          />
        </div>
      </div>

      <form class="composer" @submit.prevent="send()">
        <p v-if="sendError" class="send-error">{{ sendError }}</p>
        <div class="box" :class="{ busy: sending }">
          <textarea
            ref="composer"
            v-model="draft"
            rows="1"
            maxlength="8000"
            :placeholder="ready ? 'Pregunta o demana un canvi… (Maj+Retorn per a una línia nova)' : 'L’assistent no està disponible'"
            :disabled="!ready"
            @keydown="onKey"
          />
          <button v-if="sending" class="btn btn-outline btn-sm" type="button" @click="stop">Atura</button>
          <button v-else class="btn btn-ai btn-sm" type="submit" :disabled="!draft.trim() || !ready">
            <AppIcon name="send" :size="13" />
            Envia
          </button>
        </div>
        <p class="fineprint">
          Beta. Pot equivocar-se: revisa les xifres importants. Només llegeix; els canvis sempre els confirmes tu.
        </p>
      </form>
    </section>
  </div>
</template>

<style scoped>
.assistant {
  display: grid;
  grid-template-columns: 232px minmax(0, 1fr);
  gap: 16px;
  /* The shell pads 20px above and 40px below; the chat fills what is left. */
  height: calc(100dvh - 60px - var(--shell-inset-top));
  min-height: 420px;
}

/* ── Chats ────────────────────────────────────────────────────────────── */

.chats {
  display: flex;
  flex-direction: column;
  gap: 8px;
  min-height: 0;
}

.new {
  justify-content: flex-start;
}

.chat-list {
  display: grid;
  align-content: start;
  gap: 1px;
  margin: 0;
  padding: 0;
  overflow-y: auto;
  list-style: none;
}

.chat-list li {
  position: relative;
  display: flex;
  align-items: center;
  border-radius: var(--r-md);
}

.chat-list li:hover {
  background: var(--surface-2);
}

.chat-list li.active {
  background: var(--accent-50);
}

.chat {
  display: grid;
  flex: 1;
  gap: 1px;
  min-width: 0;
  padding: 6px 8px;
  border: 0;
  background: none;
  text-align: left;
}

.chat-title {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: var(--text-base);
  color: var(--ink-900);
}

.active .chat-title {
  color: var(--accent-700);
  font-weight: 500;
}

.chat-when {
  font-size: var(--text-xs);
  color: var(--ink-400);
}

.chat-delete {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  margin-right: 4px;
  padding: 4px 5px;
  border: 0;
  border-radius: var(--r-sm);
  background: none;
  font-size: var(--text-xs);
  color: var(--ink-400);
  opacity: 0;
}

.chat-list li:hover .chat-delete,
.chat-delete:focus-visible,
.chat-delete.confirm {
  opacity: 1;
}

.chat-delete:hover {
  color: var(--danger-700);
  background: var(--danger-100);
}

.chat-delete.confirm {
  color: var(--surface-0);
  background: var(--danger-600);
}

.chats-empty {
  padding: 4px 8px;
  font-size: var(--text-sm);
  color: var(--ink-400);
}

/* ── Chat ─────────────────────────────────────────────────────────────── */

.chat-pane {
  display: flex;
  flex-direction: column;
  min-width: 0;
  min-height: 0;
  border: 1px solid var(--line);
  border-radius: var(--r-xl);
  background: var(--surface-0);
  overflow: hidden;
}

.chat-head {
  display: flex;
  align-items: center;
  gap: 10px;
  min-height: 44px;
  padding: 0 14px;
  border-bottom: 1px solid var(--line);
}

.chat-name {
  display: flex;
  flex: 1;
  align-items: center;
  gap: 8px;
  min-width: 0;
}

.title-button,
.title-plain {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: var(--text-md);
  font-weight: 600;
  color: var(--ink-900);
}

.title-button {
  padding: 2px 4px;
  margin-left: -4px;
  border: 0;
  border-radius: var(--r-sm);
  background: none;
}

.title-button:hover {
  background: var(--surface-2);
}

.rename {
  height: 28px;
  max-width: 420px;
}

.model {
  font-family: var(--font-mono);
  font-size: var(--text-xs);
  color: var(--ink-400);
}

.thread {
  flex: 1;
  min-height: 0;
  padding: 18px 20px 8px;
  overflow-y: auto;
}

.messages {
  display: grid;
  gap: 18px;
  max-width: 920px;
  margin: 0 auto;
}

.loading-line {
  font-size: var(--text-sm);
  color: var(--ink-400);
}

.notice {
  max-width: 920px;
  margin: 0 auto 12px;
}

/* ── Welcome ──────────────────────────────────────────────────────────── */

.welcome {
  display: grid;
  justify-items: start;
  gap: 8px;
  max-width: 640px;
  margin: 6vh auto 0;
}

.welcome-mark {
  display: grid;
  place-items: center;
  width: 36px;
  height: 36px;
  border-radius: var(--r-lg);
  background: var(--ai-100);
  color: var(--ai-600);
}

.welcome-title {
  font-size: var(--text-xl);
}

.welcome-lead {
  font-size: var(--text-md);
  color: var(--ink-500);
}

.examples {
  display: grid;
  gap: 6px;
  width: 100%;
  margin-top: 8px;
}

.example {
  padding: 8px 12px;
  border: 1px solid var(--line);
  border-radius: var(--r-md);
  background: var(--surface-1);
  font-size: var(--text-base);
  color: var(--ink-700);
  text-align: left;
}

.example:hover:not(:disabled) {
  border-color: var(--ai-200);
  background: var(--ai-50);
  color: var(--ink-900);
}

/* ── Composer ─────────────────────────────────────────────────────────── */

.composer {
  padding: 10px 16px 10px;
  border-top: 1px solid var(--line);
}

.box {
  display: flex;
  align-items: flex-end;
  gap: 8px;
  max-width: 920px;
  margin: 0 auto;
  padding: 6px 6px 6px 12px;
  border: 1px solid var(--line-strong);
  border-radius: var(--r-lg);
  background: var(--surface-0);
}

.box:focus-within {
  border-color: var(--ai-400);
  box-shadow: 0 0 0 3px var(--ai-100);
}

.box.busy {
  border-color: var(--ai-200);
}

textarea {
  flex: 1;
  min-height: 28px;
  max-height: 200px;
  padding: 4px 0;
  border: 0;
  outline: none;
  background: none;
  resize: none;
  field-sizing: content;
  font-size: var(--text-md);
  line-height: 1.45;
}

textarea::placeholder {
  color: var(--ink-400);
}

.send-error {
  max-width: 920px;
  margin: 0 auto 6px;
  font-size: var(--text-sm);
  color: var(--danger-700);
}

.fineprint {
  max-width: 920px;
  margin: 6px auto 0;
  font-size: var(--text-xs);
  color: var(--ink-400);
}

@media (max-width: 860px) {
  .assistant {
    grid-template-columns: minmax(0, 1fr);
    grid-template-rows: auto minmax(0, 1fr);
    height: calc(100dvh - 110px);
  }

  .chats {
    max-height: 132px;
  }
}
</style>
