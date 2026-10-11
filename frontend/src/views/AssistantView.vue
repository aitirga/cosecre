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
import type { IconName } from '../components/icons'
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
const titleInput = ref<HTMLInputElement | null>(null)

const EXAMPLES: { icon: IconName; label: string; text: string }[] = [
  {
    icon: 'chart',
    label: 'Despesa per compte',
    text: 'Quant hem gastat per compte aquest curs? Fes-ne un gràfic per mesos.',
  },
  {
    icon: 'users',
    label: 'Proveïdors principals',
    text: 'Quins són els 10 proveïdors que més ens han facturat enguany?',
  },
  {
    icon: 'link',
    label: 'Pagaments sense justificar',
    text: 'Quines factures pagades no tenen cap moviment bancari que les justifiqui?',
  },
  {
    icon: 'clock',
    label: 'Pendents de validar',
    text: 'Quins documents porten més d’una setmana pendents de validar?',
  },
]

// ── Layout ───────────────────────────────────────────────────────────────────

/** Desktop: the chat list can fold away. Narrow: it is a drawer over the chat. */
const SIDEBAR_KEY = 'cosecre.assistant.sidebar'
const narrow = useMediaQuery('(max-width: 860px)')
const sidebarFolded = ref(readFolded())
const drawerOpen = ref(false)
const search = ref('')

function readFolded() {
  try {
    return localStorage.getItem(SIDEBAR_KEY) === 'folded'
  } catch {
    return false
  }
}

function toggleSidebar() {
  if (narrow.value) {
    drawerOpen.value = !drawerOpen.value
    return
  }
  sidebarFolded.value = !sidebarFolded.value
  try {
    localStorage.setItem(SIDEBAR_KEY, sidebarFolded.value ? 'folded' : 'open')
  } catch {
    /* private window: the fold just isn't remembered */
  }
}

watch(narrow, () => {
  drawerOpen.value = false
})

function useMediaQuery(query: string) {
  const media = window.matchMedia(query)
  const matches = ref(media.matches)
  const update = (event: MediaQueryListEvent) => (matches.value = event.matches)
  media.addEventListener('change', update)
  onBeforeUnmount(() => media.removeEventListener('change', update))
  return matches
}

/** The scroller is away from the end: offer a jump back down. */
const awayFromEnd = ref(false)

function onScroll() {
  const el = scroller.value
  if (!el) return
  awayFromEnd.value = el.scrollHeight - el.scrollTop - el.clientHeight > 240
}

function autosize() {
  const el = composer.value
  if (!el) return
  el.style.height = 'auto'
  el.style.height = `${Math.min(el.scrollHeight, 220)}px`
}

watch(draft, () => void nextTick(autosize))

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
  drawerOpen.value = false
  void router.replace({ query: { ...route.query, c: id ?? undefined } })
  if (id == null) void nextTick(() => composer.value?.focus())
}

async function scrollToEnd(force = true, smooth = false) {
  await nextTick()
  const el = scroller.value
  if (!el) return
  const nearEnd = el.scrollHeight - el.scrollTop - el.clientHeight < 160
  if (force || nearEnd) el.scrollTo({ top: el.scrollHeight, behavior: smooth ? 'smooth' : 'auto' })
  onScroll()
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
        void scrollToEnd(frame.type === 'user')
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
  void nextTick(() => titleInput.value?.select())
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
  const date = parse(iso)
  return date.toDateString() === new Date().toDateString() ? TIME.format(date) : DAY.format(date)
}

function parse(iso: string) {
  return new Date(iso.endsWith('Z') || /[+-]\d\d:\d\d$/.test(iso) ? iso : `${iso}Z`)
}

/** The chat list, filtered by the search box and grouped the way people remember chats. */
const groups = computed(() => {
  const needle = search.value.trim().toLocaleLowerCase('ca')
  const today = new Date()
  today.setHours(0, 0, 0, 0)
  const DAY_MS = 86_400_000
  const buckets: { label: string; chats: AssistantConversationSummary[] }[] = [
    { label: 'Avui', chats: [] },
    { label: 'Ahir', chats: [] },
    { label: 'Últims 7 dies', chats: [] },
    { label: 'Últims 30 dies', chats: [] },
    { label: 'Abans', chats: [] },
  ]
  for (const chat of conversations.value) {
    if (needle && !chat.title.toLocaleLowerCase('ca').includes(needle)) continue
    const age = today.getTime() - parse(chat.updated_at).getTime()
    const index = age <= 0 ? 0 : age <= DAY_MS ? 1 : age <= 7 * DAY_MS ? 2 : age <= 30 * DAY_MS ? 3 : 4
    buckets[index].chats.push(chat)
  }
  return buckets.filter((bucket) => bucket.chats.length)
})

const ready = computed(() => statusQuery.data.value?.ready ?? true)
const empty = computed(() => !activeId.value && !messages.value.length)

onBeforeUnmount(() => abort?.abort())
</script>

<template>
  <div class="assistant-page" :class="{ folded: sidebarFolded && !narrow, drawer: narrow, 'drawer-open': drawerOpen }">
    <aside class="chats" :aria-hidden="narrow && !drawerOpen ? 'true' : undefined">
      <div class="chats-head">
        <span class="chats-label">Converses</span>
        <button class="btn btn-ghost btn-icon btn-sm" type="button" title="Amaga la llista" aria-label="Amaga la llista" @click="toggleSidebar">
          <AppIcon :name="narrow ? 'close' : 'panel'" :size="14" />
        </button>
      </div>
      <button class="btn btn-outline new" type="button" @click="open(null)">
        <AppIcon name="plus" :size="14" />
        Conversa nova
      </button>
      <label v-if="conversations.length > 5" class="chat-search">
        <AppIcon name="search" :size="13" />
        <input v-model="search" type="search" placeholder="Cerca converses" aria-label="Cerca converses" />
      </label>

      <nav class="chat-groups" aria-label="Converses">
        <section v-for="group in groups" :key="group.label" class="chat-group">
          <h2 class="group-label">{{ group.label }}</h2>
          <ul class="chat-list">
            <li
              v-for="chat in group.chats"
              :key="chat.id"
              :class="{ active: chat.id === activeId }"
              @mouseleave="confirmDelete = confirmDelete === chat.id ? null : confirmDelete"
            >
              <button class="chat" type="button" :aria-current="chat.id === activeId ? 'page' : undefined" @click="open(chat.id)">
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
        </section>
        <p v-if="search && !groups.length" class="chats-empty">Cap conversa amb «{{ search }}».</p>
        <p v-else-if="!conversations.length && !listQuery.isLoading.value" class="chats-empty">
          Encara no hi ha cap conversa. Les que facis són només teves.
        </p>
      </nav>
    </aside>
    <div v-if="narrow && drawerOpen" class="scrim" @click="drawerOpen = false" />

    <section class="chat-pane">
      <header class="chat-head">
        <button
          v-if="narrow || sidebarFolded"
          class="btn btn-ghost btn-icon btn-sm"
          type="button"
          title="Mostra les converses"
          aria-label="Mostra les converses"
          @click="toggleSidebar"
        >
          <AppIcon name="panel" :size="15" />
        </button>
        <div class="chat-name">
          <input
            v-if="editingTitle"
            ref="titleInput"
            v-model="titleDraft"
            class="input rename"
            maxlength="255"
            @keydown.enter.prevent="saveRename"
            @keydown.esc="editingTitle = false"
            @blur="saveRename"
          />
          <button v-else-if="activeId && title" class="title-button" type="button" title="Canvia el nom" @click="startRename">
            <span class="title-text">{{ title }}</span>
            <AppIcon name="pencil" :size="12" class="title-edit" />
          </button>
          <span v-else class="title-plain">Assistent</span>
          <span class="badge badge-ai">beta</span>
        </div>
        <span v-if="statusQuery.data.value" class="model" :title="`Raonament: ${statusQuery.data.value.reasoning_effort}`">
          {{ statusQuery.data.value.model }}
        </span>
        <button
          v-if="(narrow || sidebarFolded) && !empty"
          class="btn btn-ghost btn-icon btn-sm"
          type="button"
          title="Conversa nova"
          aria-label="Conversa nova"
          @click="open(null)"
        >
          <AppIcon name="plus" :size="15" />
        </button>
      </header>

      <div ref="scroller" class="thread" :class="{ 'is-empty': empty }" @scroll.passive="onScroll">
        <div class="column">
          <p v-if="!ready" class="notice notice-warn">{{ statusQuery.data.value?.detail }}</p>
          <p v-if="loadError" class="notice notice-error">{{ loadError }}</p>

          <div v-if="empty" class="welcome">
            <div class="welcome-mark"><AppIcon name="sparkles" :size="20" /></div>
            <h1 class="welcome-title">Què vols saber de les dades?</h1>
            <p class="welcome-lead">
              Consulta el registre, els extractes i les sol·licituds, i en fa càlculs, taules i gràfics.
              Si li demanes un canvi, te'l proposa amb el valor d'abans i el de després: només s'aplica si el confirmes.
            </p>
            <div class="examples">
              <button
                v-for="example in EXAMPLES"
                :key="example.label"
                class="example"
                type="button"
                :disabled="!ready"
                @click="send(example.text)"
              >
                <span class="example-icon"><AppIcon :name="example.icon" :size="14" /></span>
                <span class="example-copy">
                  <span class="example-label">{{ example.label }}</span>
                  <span class="example-text">{{ example.text }}</span>
                </span>
              </button>
            </div>
          </div>

          <div v-else-if="loading" class="skeleton" aria-label="Carregant…">
            <span class="sk sk-user" />
            <span class="sk sk-line" />
            <span class="sk sk-line short" />
          </div>

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
      </div>

      <form class="composer" @submit.prevent="send()">
        <button
          v-if="awayFromEnd && !empty"
          class="to-end"
          type="button"
          title="Ves al final"
          aria-label="Ves al final"
          @click="scrollToEnd(true, true)"
        >
          <AppIcon name="arrowDown" :size="14" />
        </button>
        <div class="column">
          <p v-if="sendError" class="send-error"><AppIcon name="alert" :size="13" /> {{ sendError }}</p>
          <div class="box" :class="{ busy: sending, disabled: !ready }" @click="composer?.focus()">
            <textarea
              ref="composer"
              v-model="draft"
              rows="1"
              maxlength="8000"
              :placeholder="ready ? 'Pregunta o demana un canvi…' : 'L’assistent no està disponible'"
              :disabled="!ready"
              aria-label="Missatge per a l’assistent"
              @keydown="onKey"
            />
            <div class="box-foot">
              <span class="hint"><kbd>Retorn</kbd> envia · <kbd>Maj</kbd>+<kbd>Retorn</kbd> línia nova</span>
              <button v-if="sending" class="btn btn-outline btn-icon send" type="button" title="Atura" aria-label="Atura" @click.stop="stop">
                <AppIcon name="stop" :size="14" />
              </button>
              <button
                v-else
                class="btn btn-ai btn-icon send"
                type="submit"
                title="Envia"
                aria-label="Envia"
                :disabled="!draft.trim() || !ready"
              >
                <AppIcon name="arrowUp" :size="15" />
              </button>
            </div>
          </div>
          <p class="fineprint">Beta: pot equivocar-se, revisa les xifres importants. Els canvis sempre els confirmes tu.</p>
        </div>
      </form>
    </section>
  </div>
</template>

<style scoped>
.assistant-page {
  --chats-w: 248px;
  position: relative;
  display: grid;
  grid-template-columns: var(--chats-w) minmax(0, 1fr);
  /* The shell pads 20px above and 40px below; pull the bottom in so the chat
     sits with an even 20px gap and fills the rest of the screen. */
  height: calc(100dvh - 40px - var(--shell-inset-top));
  min-height: 420px;
  margin-bottom: -20px;
  border: 1px solid var(--line);
  border-radius: var(--r-xl);
  background: var(--surface-0);
  box-shadow: var(--shadow-xs);
  overflow: hidden;
  transition: grid-template-columns 0.18s ease;
}

.assistant-page.folded {
  grid-template-columns: 0 minmax(0, 1fr);
}

/* ── Chats ────────────────────────────────────────────────────────────── */

.chats {
  display: flex;
  flex-direction: column;
  gap: 8px;
  min-width: 0;
  min-height: 0;
  padding: 10px 8px 8px;
  border-right: 1px solid var(--line);
  background: var(--surface-1);
  overflow: hidden;
}

.folded .chats {
  visibility: hidden;
  border-right: 0;
}

.chats-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  min-height: 26px;
  padding: 0 2px 0 6px;
}

.chats-label {
  font-size: var(--text-xs);
  font-weight: 600;
  letter-spacing: 0.04em;
  text-transform: uppercase;
  color: var(--ink-400);
}

.new {
  justify-content: flex-start;
  width: 100%;
}

.chat-search {
  display: flex;
  align-items: center;
  gap: 6px;
  height: 30px;
  padding: 0 8px;
  border: 1px solid var(--line);
  border-radius: var(--r-md);
  background: var(--surface-0);
  color: var(--ink-400);
}

.chat-search:focus-within {
  border-color: var(--accent-500);
}

.chat-search input {
  flex: 1;
  min-width: 0;
  border: 0;
  outline: none;
  background: none;
  font-size: var(--text-base);
  color: var(--ink-900);
}

.chat-groups {
  display: grid;
  align-content: start;
  gap: 12px;
  min-height: 0;
  margin: 0 -8px;
  padding: 4px 8px 8px;
  overflow-y: auto;
}

.group-label {
  margin: 0 0 2px;
  padding: 0 8px;
  font-size: var(--text-xs);
  font-weight: 500;
  color: var(--ink-400);
}

.chat-list {
  display: grid;
  gap: 1px;
  margin: 0;
  padding: 0;
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
  background: var(--surface-0);
  box-shadow: inset 0 0 0 1px var(--line);
}

.chat {
  display: flex;
  flex: 1;
  align-items: baseline;
  gap: 8px;
  min-width: 0;
  padding: 6px 8px;
  border: 0;
  background: none;
  text-align: left;
}

.chat-title {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: var(--text-base);
  color: var(--ink-700);
}

.active .chat-title {
  color: var(--ink-900);
  font-weight: 500;
}

.chat-when {
  flex: none;
  font-size: var(--text-xs);
  color: var(--ink-400);
  font-variant-numeric: tabular-nums;
}

.chat-list li:hover .chat-when,
.chat-list li:focus-within .chat-when {
  visibility: hidden;
}

.chat-delete {
  position: absolute;
  right: 4px;
  display: inline-flex;
  align-items: center;
  gap: 4px;
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
  position: relative;
  display: flex;
  flex-direction: column;
  min-width: 0;
  min-height: 0;
}

.chat-head {
  display: flex;
  align-items: center;
  gap: 8px;
  min-height: 46px;
  padding: 0 10px 0 14px;
  border-bottom: 1px solid var(--line);
}

.chat-head > .btn:first-child {
  margin-left: -4px;
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
  display: inline-flex;
  align-items: center;
  gap: 6px;
  min-width: 0;
  font-size: var(--text-md);
  font-weight: 600;
  color: var(--ink-900);
}

.title-text {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.title-button {
  padding: 3px 6px;
  margin-left: -6px;
  border: 0;
  border-radius: var(--r-sm);
  background: none;
}

.title-edit {
  flex: none;
  color: var(--ink-400);
  opacity: 0;
}

.title-button:hover {
  background: var(--surface-2);
}

.title-button:hover .title-edit,
.title-button:focus-visible .title-edit {
  opacity: 1;
}

.rename {
  height: 28px;
  width: min(420px, 100%);
}

.model {
  padding: 2px 6px;
  border: 1px solid var(--line);
  border-radius: var(--r-sm);
  font-family: var(--font-mono);
  font-size: var(--text-xs);
  color: var(--ink-400);
  white-space: nowrap;
}

/* One reading column shared by the thread and the composer. */
.column {
  width: 100%;
  max-width: 780px;
  margin: 0 auto;
}

.thread {
  flex: 1;
  min-height: 0;
  padding: 24px 24px 12px;
  overflow-y: auto;
  scrollbar-gutter: stable;
}

.thread.is-empty {
  display: grid;
  align-items: center;
}

.messages {
  display: grid;
  gap: 22px;
}

.notice {
  margin-bottom: 12px;
}

.skeleton {
  display: grid;
  gap: 10px;
}

.sk {
  display: block;
  height: 12px;
  border-radius: var(--r-sm);
  background: linear-gradient(90deg, var(--surface-2), var(--surface-3), var(--surface-2));
  background-size: 200% 100%;
  animation: shimmer 1.2s linear infinite;
}

.sk-user {
  justify-self: end;
  width: 40%;
  height: 32px;
  margin-bottom: 8px;
}

.sk-line {
  width: 85%;
}

.sk-line.short {
  width: 55%;
}

@keyframes shimmer {
  to {
    background-position: -200% 0;
  }
}

/* ── Welcome ──────────────────────────────────────────────────────────── */

.welcome {
  display: grid;
  justify-items: center;
  gap: 8px;
  max-width: 640px;
  margin: 0 auto;
  padding-bottom: 4vh;
  text-align: center;
}

.welcome-mark {
  display: grid;
  place-items: center;
  width: 40px;
  height: 40px;
  margin-bottom: 4px;
  border: 1px solid var(--ai-200);
  border-radius: var(--r-xl);
  background: var(--ai-50);
  color: var(--ai-600);
}

.welcome-title {
  font-size: var(--text-2xl);
  letter-spacing: -0.01em;
}

.welcome-lead {
  max-width: 540px;
  font-size: var(--text-md);
  line-height: 1.55;
  color: var(--ink-500);
}

.examples {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 8px;
  width: 100%;
  margin-top: 16px;
}

.example {
  display: flex;
  align-items: flex-start;
  gap: 10px;
  padding: 10px 12px;
  border: 1px solid var(--line);
  border-radius: var(--r-lg);
  background: var(--surface-0);
  text-align: left;
  transition:
    border-color 0.12s ease,
    background-color 0.12s ease;
}

.example:hover:not(:disabled) {
  border-color: var(--ai-200);
  background: var(--ai-50);
}

.example:disabled {
  opacity: 0.55;
  cursor: not-allowed;
}

.example-icon {
  display: grid;
  flex: none;
  place-items: center;
  width: 26px;
  height: 26px;
  border-radius: var(--r-md);
  background: var(--surface-2);
  color: var(--ink-500);
}

.example:hover:not(:disabled) .example-icon {
  background: var(--ai-100);
  color: var(--ai-600);
}

.example-copy {
  display: grid;
  gap: 2px;
  min-width: 0;
}

.example-label {
  font-size: var(--text-base);
  font-weight: 600;
  color: var(--ink-900);
}

.example-text {
  font-size: var(--text-sm);
  line-height: 1.4;
  color: var(--ink-500);
}

/* ── Composer ─────────────────────────────────────────────────────────── */

.composer {
  position: relative;
  padding: 8px 24px 12px;
}

.to-end {
  position: absolute;
  top: -40px;
  left: 50%;
  display: grid;
  place-items: center;
  width: 30px;
  height: 30px;
  border: 1px solid var(--line-strong);
  border-radius: var(--r-full);
  background: var(--surface-0);
  box-shadow: var(--shadow-md);
  color: var(--ink-700);
  transform: translateX(-50%);
}

.to-end:hover {
  background: var(--surface-2);
}

.box {
  display: grid;
  gap: 4px;
  padding: 10px 10px 8px 14px;
  border: 1px solid var(--line-strong);
  border-radius: var(--r-xl);
  background: var(--surface-0);
  box-shadow: var(--shadow-sm);
  cursor: text;
  transition:
    border-color 0.12s ease,
    box-shadow 0.12s ease;
}

.box:focus-within {
  border-color: var(--ai-400);
  box-shadow:
    0 0 0 3px var(--ai-100),
    var(--shadow-sm);
}

.box.busy {
  border-color: var(--ai-200);
}

.box.disabled {
  background: var(--surface-1);
  cursor: not-allowed;
}

textarea {
  width: 100%;
  min-height: 24px;
  max-height: 220px;
  padding: 2px 0;
  border: 0;
  outline: none;
  background: none;
  resize: none;
  font-size: var(--text-md);
  line-height: 1.5;
  color: var(--ink-900);
}

textarea::placeholder {
  color: var(--ink-400);
}

.box-foot {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}

.hint {
  font-size: var(--text-xs);
  color: var(--ink-400);
}

kbd {
  padding: 0 4px;
  border: 1px solid var(--line);
  border-bottom-width: 2px;
  border-radius: var(--r-xs);
  background: var(--surface-1);
  font-family: inherit;
  font-size: 10px;
  color: var(--ink-500);
}

.send {
  margin-left: auto;
  border-radius: var(--r-lg);
}

.send-error {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-bottom: 6px;
  font-size: var(--text-sm);
  color: var(--danger-700);
}

.fineprint {
  margin-top: 6px;
  font-size: var(--text-xs);
  color: var(--ink-400);
  text-align: center;
}

/* ── Narrow: the list becomes a drawer, the chat goes edge to edge ───── */

@media (max-width: 860px) {
  .assistant-page {
    grid-template-columns: minmax(0, 1fr);
    height: calc(100dvh - var(--topbar-h, 52px));
    min-height: 0;
    margin: -16px -14px -32px;
    border: 0;
    border-radius: 0;
    box-shadow: none;
  }

  .chats {
    position: absolute;
    top: 0;
    bottom: 0;
    left: 0;
    z-index: 20;
    width: min(86%, 300px);
    box-shadow: var(--shadow-lg);
    transform: translateX(-100%);
    visibility: hidden;
    transition:
      transform 0.18s ease,
      visibility 0s linear 0.18s;
  }

  .drawer-open .chats {
    transform: none;
    visibility: visible;
    transition: transform 0.18s ease;
  }

  .scrim {
    position: absolute;
    inset: 0;
    z-index: 10;
    background: rgba(27, 44, 70, 0.3);
  }

  .chat-head {
    padding: 0 6px 0 10px;
  }

  .model {
    display: none;
  }

  .thread {
    padding: 16px 14px 8px;
  }

  .composer {
    padding: 6px 10px calc(8px + env(safe-area-inset-bottom));
  }

  .hint {
    display: none;
  }

  .welcome-title {
    font-size: var(--text-xl);
  }

  .examples {
    grid-template-columns: minmax(0, 1fr);
  }

  .fineprint {
    display: none;
  }

  /* Touch: delete stays reachable without hover. */
  .chat-delete {
    position: static;
    opacity: 1;
  }

  .chat-list li .chat-when {
    visibility: visible;
  }
}
</style>
