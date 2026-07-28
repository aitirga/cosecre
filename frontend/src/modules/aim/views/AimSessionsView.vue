<script setup lang="ts">
import { useMutation, useQuery, useQueryClient } from '@tanstack/vue-query'
import { computed, ref } from 'vue'
import { useRouter } from 'vue-router'

import { ApiError } from '../../../api/client'
import AppIcon from '../../../components/AppIcon.vue'
import { aimApi } from '../api'
import { CA } from '../strings'

const router = useRouter()
const queryClient = useQueryClient()

const sessions = useQuery({
  queryKey: ['aim-sessions'],
  queryFn: aimApi.sessions,
  // A waiting session gains students while the teacher watches this screen.
  refetchInterval: 10_000,
})
const exercises = useQuery({
  queryKey: ['aim-exercises', 'mine'],
  queryFn: () => aimApi.exercises({ scope: 'mine' }),
})

const error = ref<string | null>(null)
const creating = ref(false)
const chosen = ref<number | null>(null)

/** Only a refined exercise has anything for a tutor to work from. */
const runnable = computed(() => exercises.data.value?.filter((item) => item.refined) ?? [])

function fail(cause: unknown) {
  error.value = cause instanceof ApiError ? cause.message : CA.errors.generic
}

function refresh() {
  void queryClient.invalidateQueries({ queryKey: ['aim-sessions'] })
}

const create = useMutation({
  mutationFn: (exerciseId: number) => aimApi.createSession(exerciseId),
  onSuccess: (created) => {
    creating.value = false
    error.value = null
    void router.push({ name: 'aim-monitor', params: { id: created.id } })
  },
  onError: fail,
})

const start = useMutation({
  mutationFn: (id: string) => aimApi.startSession(id),
  onSuccess: refresh,
  onError: fail,
})

const end = useMutation({
  mutationFn: (id: string) => aimApi.endSession(id),
  onSuccess: refresh,
  onError: fail,
})

const STATUS_LABEL = {
  waiting: CA.sessions.waiting,
  live: CA.sessions.live,
  ended: CA.sessions.ended,
} as const

const STATUS_BADGE = {
  waiting: 'badge-gold',
  live: 'badge-olive',
  ended: 'badge-neutral',
} as const

function openCreate() {
  creating.value = true
  chosen.value = runnable.value[0]?.id ?? null
  void exercises.refetch()
}
</script>

<template>
  <section>
    <header class="page-head">
      <div>
        <h1 class="page-title">{{ CA.sessions.title }}</h1>
        <p class="page-lead">{{ CA.sessions.lead }}</p>
      </div>
      <button class="btn btn-primary" type="button" @click="openCreate">
        <AppIcon name="plus" :size="15" />
        {{ CA.sessions.create }}
      </button>
    </header>

    <p v-if="error" class="notice-error">{{ error }}</p>

    <p v-if="sessions.isPending.value" class="muted">{{ CA.common.loading }}</p>
    <div v-else-if="!sessions.data.value?.length" class="card">
      <div class="card-body"><p class="empty">{{ CA.sessions.empty }}</p></div>
    </div>

    <div v-else class="table-scroll">
      <table class="table">
        <thead>
          <tr>
            <th>{{ CA.sessions.title }}</th>
            <th>{{ CA.sessions.code }}</th>
            <th class="num">{{ CA.sessions.budget }}</th>
            <th></th>
            <th class="actions-col"></th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="item in sessions.data.value" :key="item.id">
            <td>
              <RouterLink class="link" :to="{ name: 'aim-monitor', params: { id: item.id } }">
                {{ item.exercise_title }}
              </RouterLink>
              <span class="sub">{{ CA.sessions.students(item.participant_count) }}</span>
            </td>
            <td><code class="mono code">{{ item.join_code }}</code></td>
            <td class="num">{{ item.token_budget.toLocaleString('ca') }}</td>
            <td>
              <span class="badge" :class="STATUS_BADGE[item.status]">
                {{ STATUS_LABEL[item.status] }}
              </span>
            </td>
            <td class="actions">
              <button
                v-if="item.status === 'waiting'"
                class="btn btn-primary btn-sm"
                type="button"
                :disabled="start.isPending.value"
                @click="start.mutate(item.id)"
              >
                <AppIcon name="play" :size="13" />
                {{ CA.sessions.start }}
              </button>
              <button
                v-if="item.status === 'live'"
                class="btn btn-outline btn-sm"
                type="button"
                :disabled="end.isPending.value"
                @click="end.mutate(item.id)"
              >
                {{ CA.sessions.end }}
              </button>
              <RouterLink
                class="btn btn-ghost btn-sm"
                :to="{ name: 'aim-monitor', params: { id: item.id } }"
              >
                {{ CA.sessions.watch }}
              </RouterLink>
            </td>
          </tr>
        </tbody>
      </table>
    </div>

    <Teleport to="body">
      <div v-if="creating" class="overlay" @click.self="creating = false">
        <div class="dialog" role="dialog" aria-modal="true">
          <h2 class="dialog-title">{{ CA.sessions.createTitle }}</h2>
          <p v-if="!runnable.length" class="empty">{{ CA.sessions.noExercises }}</p>
          <label v-else class="field">
            <select v-model="chosen" class="select">
              <option v-for="item in runnable" :key="item.id" :value="item.id">
                {{ item.title }}
              </option>
            </select>
          </label>
          <div class="dialog-actions">
            <button class="btn btn-ghost" type="button" @click="creating = false">
              {{ CA.roster.cancel }}
            </button>
            <button
              class="btn btn-primary"
              type="button"
              :disabled="create.isPending.value || chosen === null"
              @click="chosen !== null && create.mutate(chosen)"
            >
              {{ CA.sessions.create }}
            </button>
          </div>
        </div>
      </div>
    </Teleport>
  </section>
</template>

<style scoped>
.table-scroll {
  margin-top: 12px;
}

.link {
  color: var(--ink-900);
  font-weight: 500;
}

.link:hover {
  color: var(--accent-700);
}

.sub {
  display: block;
  font-size: var(--text-xs);
  color: var(--ink-400);
}

.code {
  letter-spacing: 0.08em;
  font-weight: 600;
}

.actions-col {
  width: 1%;
}
</style>
