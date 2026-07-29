<script setup lang="ts">
/**
 * The student's conversation with their tutor.
 *
 * Sending is two calls on purpose — see `api/aim/chat.py`. The reply is read
 * as a stream and rendered as it arrives; the in-flight text lives here, not in
 * the query cache, so a focus refetch cannot wipe a half-written answer.
 */
import { useMutation, useQuery, useQueryClient } from '@tanstack/vue-query'
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'

import { ApiError, fetchBlobUrl } from '../../../api/client'
import AppIcon from '../../../components/AppIcon.vue'
import CameraCapture from '../../../components/CameraCapture.vue'
import { aimApi } from '../api'
import { useTutorStream } from '../composables/useTutorStream'
import { CA } from '../strings'
import type { AimAttachment } from '../types'
import AimBudgetBar from './AimBudgetBar.vue'

const props = defineProps<{ participantId: number; tokensUsed: number; tokenBudget: number }>()
const emit = defineEmits<{ spent: [used: number] }>()

const queryClient = useQueryClient()
const { pending, streaming, error: streamError, run } = useTutorStream()

const draft = ref('')
const staged = ref<AimAttachment[]>([])
const cameraOpen = ref(false)
const uploadError = ref<string | null>(null)
const scroller = ref<HTMLElement | null>(null)
const fileInput = ref<HTMLInputElement | null>(null)

const transcript = useQuery({
  queryKey: computed(() => ['aim-transcript', props.participantId]),
  queryFn: () => aimApi.transcript(props.participantId),
})

const spent = computed(() => props.tokensUsed)
const outOfBudget = computed(() => spent.value >= props.tokenBudget && props.tokenBudget > 0)
const busy = computed(() => streaming.value || send.isPending.value)

/** Within this of the end counts as "following along". */
const STICK_THRESHOLD = 80

/**
 * Follow the conversation down, unless the student has scrolled back to
 * re-read something — yanking them away mid-sentence is worse than a message
 * arriving off-screen.
 *
 * Driven by a `MutationObserver` rather than a watcher on the transcript,
 * because what needs to be reacted to is the *rendered height* changing: a
 * streamed token, a message arriving, and a photo finishing loading all move
 * the bottom, and only one of those is a reactive value this component owns.
 */
let follow = true
let observer: MutationObserver | null = null

function onScroll() {
  const element = scroller.value
  if (!element) return
  follow = element.scrollHeight - element.clientHeight - element.scrollTop < STICK_THRESHOLD
}

onMounted(() => {
  const element = scroller.value
  if (!element) return
  observer = new MutationObserver(() => {
    if (!follow) return
    // Assigned rather than smooth-scrolled: a smooth scroll is dropped while
    // the tab is hidden, which would leave the log stuck on return.
    element.scrollTop = element.scrollHeight
  })
  observer.observe(element, { childList: true, subtree: true, characterData: true })
})

onBeforeUnmount(() => observer?.disconnect())

// ── Photos ──────────────────────────────────────────────────────────────────
const upload = useMutation({
  mutationFn: (file: File) => aimApi.uploadAttachment(props.participantId, file),
  onSuccess: (attachment) => {
    uploadError.value = null
    staged.value = [...staged.value, attachment]
    cameraOpen.value = false
  },
  onError: (cause) => {
    uploadError.value = cause instanceof ApiError ? cause.message : CA.errors.photo
  },
})

function pickFile(event: Event) {
  const file = (event.target as HTMLInputElement).files?.[0]
  if (file) upload.mutate(file)
  if (fileInput.value) fileInput.value.value = ''
}

/**
 * Attachment URLs are fetched rather than linked: the endpoint needs a bearer
 * token, so an `<img src>` pointing at it would 401. The object URL is revoked
 * when the element goes away.
 */
const photoUrls = ref<Record<number, string>>({})

async function loadPhoto(attachment: AimAttachment) {
  if (photoUrls.value[attachment.id]) return
  try {
    photoUrls.value[attachment.id] = await fetchBlobUrl(`/aim/attachments/${attachment.id}/file`)
  } catch {
    /* a thumbnail that will not load is not worth an error banner */
  }
}

watch(
  () => transcript.data.value,
  (messages) => {
    for (const message of messages ?? []) {
      for (const attachment of message.attachments) void loadPhoto(attachment)
    }
  },
  { immediate: true },
)

// ── Sending ─────────────────────────────────────────────────────────────────
const send = useMutation({
  mutationFn: () =>
    aimApi.sendMessage(
      props.participantId,
      draft.value.trim(),
      staged.value.map((item) => item.id),
    ),
  onSuccess: async (sent) => {
    draft.value = ''
    staged.value = []
    uploadError.value = null
    await queryClient.invalidateQueries({ queryKey: ['aim-transcript', props.participantId] })

    const totals = await run(sent.reply.id)
    if (totals) emit('spent', totals.tokensUsed)
    // Only now, once the answer is whole, does the cache learn about it.
    await queryClient.invalidateQueries({ queryKey: ['aim-transcript', props.participantId] })
  },
  onError: (cause) => {
    uploadError.value = cause instanceof ApiError ? cause.message : CA.errors.generic
  },
})

function submit() {
  if (!draft.value.trim() || busy.value || outOfBudget.value) return
  send.mutate()
}

/** Enter sends, Shift+Enter is a newline — what a chat box is expected to do. */
function onKeydown(event: KeyboardEvent) {
  if (event.key === 'Enter' && !event.shiftKey) {
    event.preventDefault()
    submit()
  }
}

/** Retry a turn whose stream died, without re-asking the question. */
function retry() {
  const last = transcript.data.value?.at(-1)
  if (last?.role === 'assistant') void run(last.id)
}
</script>

<template>
  <section class="chat card">
    <header class="card-head">
      <h2 class="card-title">{{ CA.chat.title }}</h2>
      <AimBudgetBar :used="spent" :budget="tokenBudget" />
    </header>

    <div ref="scroller" class="log" @scroll="onScroll">
      <p v-if="!transcript.data.value?.length" class="opener">{{ CA.chat.opener }}</p>

      <article
        v-for="message in transcript.data.value"
        :key="message.id"
        class="turn"
        :class="message.role"
      >
        <span class="who">{{ message.role === 'user' ? CA.chat.you : CA.chat.tutor }}</span>
        <div class="bubble">
          <p v-if="message.content" class="text">{{ message.content }}</p>
          <p v-else-if="message.status === 'streaming'" class="text subtle">
            {{ CA.chat.thinking }}
          </p>
          <div v-if="message.attachments.length" class="shots">
            <img
              v-for="attachment in message.attachments"
              :key="attachment.id"
              :src="photoUrls[attachment.id]"
              :alt="attachment.source_file_name"
            />
          </div>
        </div>
        <p v-if="message.status === 'failed'" class="notice-error turn-error">
          {{ message.error_message || CA.errors.stream }}
          <button class="btn btn-outline btn-sm" type="button" @click="retry">
            {{ CA.common.retry }}
          </button>
        </p>
      </article>

      <!-- The in-flight answer, held outside the cache. -->
      <article v-if="streaming || pending" class="turn assistant">
        <span class="who">{{ CA.chat.tutor }}</span>
        <div class="bubble">
          <p class="text">
            {{ pending }}<span v-if="streaming" class="caret" aria-hidden="true" />
          </p>
        </div>
      </article>

      <p v-if="streamError" class="notice-error">
        {{ streamError }}
        <button class="btn btn-outline btn-sm" type="button" @click="retry">
          {{ CA.common.retry }}
        </button>
      </p>
    </div>

    <footer class="composer">
      <p v-if="uploadError" class="notice-error">{{ uploadError }}</p>
      <p v-if="outOfBudget" class="notice-info">{{ CA.chat.budgetSpent }}</p>

      <ul v-if="staged.length" class="staged">
        <li v-for="item in staged" :key="item.id">
          <AppIcon name="image" :size="14" />
          <span class="truncate">{{ item.source_file_name }}</span>
          <button
            class="btn btn-ghost btn-icon btn-sm"
            type="button"
            :title="CA.chat.remove"
            @click="staged = staged.filter((each) => each.id !== item.id)"
          >
            <AppIcon name="close" :size="13" />
          </button>
        </li>
      </ul>

      <div class="row">
        <textarea
          v-model="draft"
          class="textarea"
          rows="2"
          :placeholder="CA.chat.placeholder"
          :disabled="outOfBudget"
          @keydown="onKeydown"
        />
        <div class="tools">
          <button
            class="btn btn-ghost btn-icon"
            type="button"
            :title="CA.chat.photo"
            :disabled="busy || outOfBudget"
            @click="cameraOpen = true"
          >
            <AppIcon name="camera" />
          </button>
          <button
            class="btn btn-ghost btn-icon"
            type="button"
            :title="CA.chat.attach"
            :disabled="busy || outOfBudget"
            @click="fileInput?.click()"
          >
            <AppIcon name="image" />
          </button>
          <button
            class="btn btn-primary"
            type="button"
            :disabled="busy || outOfBudget || !draft.trim()"
            @click="submit"
          >
            {{ CA.chat.send }}
          </button>
        </div>
      </div>

      <input
        ref="fileInput"
        class="sr-only"
        type="file"
        accept="image/png,image/jpeg"
        @change="pickFile"
      />
    </footer>

    <Teleport to="body">
      <div v-if="cameraOpen" class="overlay" @click.self="cameraOpen = false">
        <div class="dialog" role="dialog" aria-modal="true">
          <h2 class="dialog-title">{{ CA.chat.photo }}</h2>
          <CameraCapture auto-start @captured="upload.mutate($event)" />
          <div class="dialog-actions">
            <button class="btn btn-ghost" type="button" @click="cameraOpen = false">
              {{ CA.roster.cancel }}
            </button>
          </div>
        </div>
      </div>
    </Teleport>
  </section>
</template>

<style scoped>
.chat {
  display: grid;
  grid-template-rows: auto minmax(0, 1fr) auto;
  height: min(70vh, 620px);
}

.log {
  overflow-y: auto;
  padding: 14px 16px;
  display: grid;
  gap: 12px;
  align-content: start;
}

.opener {
  font-size: var(--text-base);
  color: var(--ink-400);
  text-align: center;
  max-width: 44ch;
  justify-self: center;
  padding: 24px 0;
}

.turn {
  display: grid;
  gap: 3px;
  max-width: 80%;
}

.turn.user {
  justify-self: end;
  justify-items: end;
}

.who {
  font-size: var(--text-xs);
  color: var(--ink-400);
}

.bubble {
  padding: 8px 11px;
  border-radius: var(--r-lg);
  background: var(--surface-0);
  border: 1px solid var(--line);
}

/* The student's own words are the tinted ones; the tutor does most of the
   talking, so it gets the plain surface. */
.turn.user .bubble {
  background: var(--aim-red-100);
  border-color: var(--aim-red-200);
}

.text {
  font-size: var(--text-base);
  line-height: 1.55;
  white-space: pre-wrap;
}

.caret {
  display: inline-block;
  width: 2px;
  height: 1em;
  margin-left: 2px;
  vertical-align: text-bottom;
  background: var(--accent-700);
  animation: blink 1s steps(2, start) infinite;
}

@keyframes blink {
  50% {
    opacity: 0;
  }
}

.shots {
  display: flex;
  gap: 6px;
  flex-wrap: wrap;
  margin-top: 6px;
}

.shots img {
  max-width: 180px;
  max-height: 180px;
  border-radius: var(--r-md);
  border: 1px solid var(--line);
}

.turn-error {
  display: flex;
  align-items: center;
  gap: 8px;
}

.composer {
  display: grid;
  gap: 8px;
  padding: 12px 16px;
  border-top: 1px solid var(--line);
}

.staged {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin: 0;
  padding: 0;
  list-style: none;
}

.staged li {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  max-width: 220px;
  padding: 3px 4px 3px 8px;
  border: 1px solid var(--line);
  border-radius: var(--r-full);
  background: var(--surface-0);
  font-size: var(--text-xs);
  color: var(--ink-500);
}

.row {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  gap: 8px;
  align-items: end;
}

.textarea {
  resize: none;
}

.tools {
  display: flex;
  align-items: center;
  gap: 4px;
}

@media (max-width: 640px) {
  .turn {
    max-width: 92%;
  }
}
</style>
