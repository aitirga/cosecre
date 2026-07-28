<script setup lang="ts">
/**
 * The authoring wizard.
 *
 * Six steps, the teacher's own words on the left and what the tutor will
 * actually work from on the right. The split matters: the teacher is never
 * editing the model's output, they are editing their notes and watching the
 * exercise follow.
 */
import { useMutation, useQuery, useQueryClient } from '@tanstack/vue-query'
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import { ApiError } from '../../../api/client'
import AppIcon from '../../../components/AppIcon.vue'
import { aimApi } from '../api'
import AimPlotCard from '../plot/AimPlotCard.vue'
import { CA } from '../strings'
import type { AimRawBlocks } from '../types'

const route = useRoute()
const router = useRouter()
const queryClient = useQueryClient()

const exerciseId = computed(() => Number(route.params.id))

const STEPS = [
  { key: 'title', label: CA.wizard.steps.title },
  { key: 'statement', label: CA.wizard.steps.statement },
  { key: 'difficulty', label: CA.wizard.steps.difficulty },
  { key: 'issues', label: CA.wizard.steps.issues },
  { key: 'plots', label: CA.wizard.steps.plots },
  { key: 'review', label: CA.wizard.steps.review },
] as const

type StepKey = (typeof STEPS)[number]['key']

const step = ref(0)
const current = computed(() => STEPS[step.value])
const blocks = ref<AimRawBlocks>({})
const focus = ref('')
const error = ref<string | null>(null)
const notice = ref<string | null>(null)
const savingState = ref<'idle' | 'saving' | 'saved'>('idle')
const chosenTopics = ref<string[]>([])
const level = ref('')

const exercise = useQuery({
  queryKey: computed(() => ['aim-exercise', exerciseId.value]),
  queryFn: () => aimApi.exercise(exerciseId.value),
})
const topics = useQuery({ queryKey: ['aim-topics'], queryFn: aimApi.topics })

const refined = computed(() => exercise.data.value?.current?.refined ?? null)
const plots = computed(() => exercise.data.value?.current?.plots ?? [])

/** Seed the editors once the exercise arrives, without clobbering local edits. */
watch(
  () => exercise.data.value,
  (data) => {
    if (!data || savingState.value === 'saving') return
    blocks.value = { ...(data.current?.raw_blocks ?? {}) }
    if (!blocks.value.title) blocks.value.title = data.title
    chosenTopics.value = [...data.topics]
    level.value = data.level
  },
  { immediate: true },
)

function fail(cause: unknown) {
  error.value = cause instanceof ApiError ? cause.message : CA.errors.generic
  notice.value = null
}

// ── Autosave ────────────────────────────────────────────────────────────────
// Debounced rather than per-keystroke: the endpoint rewrites a row, and a
// teacher typing a statement would otherwise send one request per character.
let saveTimer: ReturnType<typeof setTimeout> | undefined

const saveDraft = useMutation({
  mutationFn: (payload: AimRawBlocks) => aimApi.saveDraft(exerciseId.value, payload),
  onSuccess: () => {
    savingState.value = 'saved'
    void queryClient.invalidateQueries({ queryKey: ['aim-exercises'] })
  },
  onError: (cause) => {
    savingState.value = 'idle'
    fail(cause)
  },
})

watch(
  blocks,
  (value) => {
    if (!exercise.data.value) return
    clearTimeout(saveTimer)
    savingState.value = 'saving'
    const snapshot = { ...value }
    saveTimer = setTimeout(() => saveDraft.mutate(snapshot), 700)
  },
  { deep: true },
)

onBeforeUnmount(() => clearTimeout(saveTimer))

// ── Model calls ─────────────────────────────────────────────────────────────
const refine = useMutation({
  mutationFn: () => aimApi.refine(exerciseId.value, blocks.value, focus.value.trim() || undefined),
  onSuccess: () => {
    error.value = null
    focus.value = ''
    void exercise.refetch()
    void queryClient.invalidateQueries({ queryKey: ['aim-exercises'] })
  },
  onError: fail,
})

const generatePlots = useMutation({
  mutationFn: () => {
    const wanted = (blocks.value.plots ?? '')
      .split('\n')
      .map((line) => line.trim())
      .filter(Boolean)
    return aimApi.generatePlots(exerciseId.value, wanted)
  },
  onSuccess: () => {
    error.value = null
    void exercise.refetch()
  },
  onError: fail,
})

const publish = useMutation({
  mutationFn: () => aimApi.publish(exerciseId.value, chosenTopics.value, level.value.trim()),
  onSuccess: () => {
    error.value = null
    notice.value = CA.wizard.published
    void exercise.refetch()
    void queryClient.invalidateQueries({ queryKey: ['aim-exercises'] })
  },
  onError: fail,
})

function toggleTopic(slug: string) {
  chosenTopics.value = chosenTopics.value.includes(slug)
    ? chosenTopics.value.filter((item) => item !== slug)
    : [...chosenTopics.value, slug]
}

const editorKey = computed(() => current.value.key as Exclude<StepKey, 'review'>)
const busy = computed(() => refine.isPending.value || generatePlots.isPending.value)
</script>

<template>
  <section class="wizard">
    <header class="page-head">
      <div>
        <button class="btn btn-ghost btn-sm" type="button" @click="router.push({ name: 'aim-exercises' })">
          <AppIcon name="chevron" :size="14" class="flip" />
          {{ CA.exercises.title }}
        </button>
        <h1 class="page-title">{{ exercise.data.value?.title || CA.common.loading }}</h1>
      </div>
      <span class="save-state muted">
        {{ savingState === 'saving' ? CA.wizard.saving : savingState === 'saved' ? CA.wizard.saved : '' }}
      </span>
    </header>

    <ol class="steps">
      <li v-for="(item, index) in STEPS" :key="item.key">
        <button
          class="step"
          :class="{ active: index === step, done: index < step }"
          type="button"
          @click="step = index"
        >
          <span class="step-index">{{ index + 1 }}</span>
          {{ item.label }}
        </button>
      </li>
    </ol>

    <p v-if="error" class="notice-error">{{ error }}</p>
    <p v-if="notice" class="notice-success">{{ notice }}</p>

    <div class="split">
      <!-- ── Left: the teacher's own words ───────────────────────────────── -->
      <div class="card">
        <div class="card-head">
          <h2 class="card-title">{{ current.label }}</h2>
        </div>
        <div class="card-body pane">
          <p class="hint">{{ CA.wizard.help[current.key] }}</p>

          <template v-if="current.key === 'title'">
            <label class="field">
              <input v-model="blocks.title" class="input" type="text" />
            </label>
          </template>

          <template v-else-if="current.key === 'review'">
            <label class="field">
              <span class="label">{{ CA.wizard.level }}</span>
              <input
                v-model="level"
                class="input"
                type="text"
                :placeholder="CA.wizard.levelPlaceholder"
              />
            </label>
            <div class="field">
              <span class="label">{{ CA.wizard.topics }}</span>
              <div class="topic-picker">
                <button
                  v-for="topic in topics.data.value"
                  :key="topic.slug"
                  class="badge"
                  :class="chosenTopics.includes(topic.slug) ? 'badge-accent' : 'badge-neutral'"
                  type="button"
                  @click="toggleTopic(topic.slug)"
                >
                  {{ topic.label }}
                </button>
              </div>
            </div>
            <button
              class="btn btn-primary"
              type="button"
              :disabled="publish.isPending.value || !refined"
              @click="publish.mutate()"
            >
              {{ CA.wizard.publish }}
            </button>
          </template>

          <template v-else>
            <label class="field">
              <textarea
                v-model="blocks[editorKey]"
                class="textarea tall"
                :placeholder="CA.wizard.placeholders[editorKey as keyof typeof CA.wizard.placeholders]"
              />
            </label>
          </template>

          <div v-if="current.key === 'plots'" class="pane-action">
            <button
              class="btn btn-outline"
              type="button"
              :disabled="busy"
              @click="generatePlots.mutate()"
            >
              <AppIcon name="sparkles" :size="15" />
              {{ generatePlots.isPending.value ? CA.wizard.generatingPlots : CA.wizard.generatePlots }}
            </button>
          </div>

          <div v-else-if="current.key !== 'review'" class="pane-action">
            <label class="field">
              <span class="label">{{ CA.wizard.focus }}</span>
              <input
                v-model="focus"
                class="input"
                type="text"
                :placeholder="CA.wizard.focusPlaceholder"
              />
            </label>
            <button class="btn btn-primary" type="button" :disabled="busy" @click="refine.mutate()">
              <AppIcon name="sparkles" :size="15" />
              {{
                refine.isPending.value
                  ? CA.wizard.refining
                  : refined
                    ? CA.wizard.refineAgain
                    : CA.wizard.refine
              }}
            </button>
          </div>

          <nav class="pager">
            <button
              class="btn btn-ghost btn-sm"
              type="button"
              :disabled="step === 0"
              @click="step -= 1"
            >
              {{ CA.wizard.back }}
            </button>
            <button
              class="btn btn-ghost btn-sm"
              type="button"
              :disabled="step === STEPS.length - 1"
              @click="step += 1"
            >
              {{ CA.wizard.next }}
            </button>
          </nav>
        </div>
      </div>

      <!-- ── Right: what the tutor will work from ────────────────────────── -->
      <div class="card preview">
        <div class="card-head">
          <h2 class="card-title">{{ CA.wizard.steps.review }}</h2>
        </div>
        <div class="card-body">
          <p v-if="!refined" class="empty">{{ CA.wizard.notRefinedYet }}</p>
          <template v-else>
            <h3 class="preview-title">{{ refined.title }}</h3>
            <p class="statement">{{ refined.statement_md }}</p>

            <section v-if="refined.difficulty_ladder.length" class="block">
              <h4 class="block-title">{{ CA.wizard.ladder }}</h4>
              <ol class="ladder">
                <li v-for="rung in refined.difficulty_ladder" :key="rung.step">
                  <strong>{{ rung.label }}</strong>
                  <p>{{ rung.prompt }}</p>
                  <p class="aside">{{ CA.wizard.escalation }}: {{ rung.escalation }}</p>
                </li>
              </ol>
            </section>

            <section v-if="refined.anticipated_issues.length" class="block">
              <h4 class="block-title">{{ CA.wizard.issuesHeading }}</h4>
              <ul class="issues">
                <li v-for="issue in refined.anticipated_issues" :key="issue.issue">
                  <strong>{{ issue.issue }}</strong>
                  <p class="aside">{{ CA.wizard.signal }}: {{ issue.signal }}</p>
                  <p class="aside">{{ CA.wizard.hint }}: {{ issue.hint }}</p>
                </li>
              </ul>
            </section>

            <section v-if="plots.length" class="block plots">
              <AimPlotCard
                v-for="(spec, index) in plots"
                :key="index"
                :spec="spec"
                regenerable
                @regenerate="generatePlots.mutate()"
              />
            </section>
          </template>
        </div>
      </div>
    </div>
  </section>
</template>

<style scoped>
.flip {
  transform: rotate(180deg);
}

.save-state {
  font-size: var(--text-xs);
  align-self: center;
}

.steps {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
  margin: 14px 0 0;
  padding: 0;
  list-style: none;
}

.step {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 5px 10px;
  border: 1px solid var(--line);
  border-radius: var(--r-md);
  background: var(--surface-0);
  font-size: var(--text-sm);
  color: var(--ink-500);
}

.step:hover {
  border-color: var(--line-strong);
}

.step.active {
  background: var(--accent-100);
  border-color: var(--accent-200);
  color: var(--accent-700);
}

.step-index {
  display: grid;
  place-items: center;
  width: 16px;
  height: 16px;
  border-radius: var(--r-full);
  background: var(--surface-2);
  font-size: 10px;
  font-weight: 700;
}

.step.active .step-index {
  background: var(--accent-700);
  color: var(--surface-0);
}

.step.done .step-index {
  background: var(--olive-100);
  color: var(--olive-700);
}

.split {
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(0, 1fr);
  gap: 10px;
  margin-top: 12px;
  align-items: start;
}

.pane {
  display: grid;
  gap: 10px;
}

.textarea.tall {
  min-height: 190px;
  resize: vertical;
}

.pane-action {
  display: grid;
  gap: 8px;
  padding-top: 2px;
  border-top: 1px solid var(--line);
}

.pager {
  display: flex;
  justify-content: space-between;
}

.topic-picker {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
}

.topic-picker .badge {
  cursor: pointer;
}

.preview .card-body {
  display: grid;
  gap: 12px;
}

.preview-title {
  font-size: var(--text-md);
}

.statement {
  font-size: var(--text-base);
  color: var(--ink-700);
  white-space: pre-wrap;
}

.block-title {
  font-size: var(--text-xs);
  text-transform: uppercase;
  letter-spacing: 0.04em;
  color: var(--ink-400);
  margin-bottom: 6px;
}

.ladder,
.issues {
  display: grid;
  gap: 8px;
  margin: 0;
  padding: 0 0 0 16px;
  font-size: var(--text-base);
}

.issues {
  padding-left: 0;
  list-style: none;
}

.aside {
  color: var(--ink-400);
  font-size: var(--text-sm);
}

.plots {
  display: grid;
  gap: 12px;
}

@media (max-width: 1040px) {
  .split {
    grid-template-columns: minmax(0, 1fr);
  }
}
</style>
