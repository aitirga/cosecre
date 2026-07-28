<script setup lang="ts">
/**
 * What every student in one session is doing.
 *
 * Polled rather than pushed, at the cadence the inbox already uses: 2s while
 * the class is actually running, 15s once it is not. The hub has no realtime
 * transport, and a teacher glancing at a projector does not need one.
 */
import { useMutation, useQuery, useQueryClient } from '@tanstack/vue-query'
import { computed, ref } from 'vue'
import { useRoute } from 'vue-router'

import { ApiError } from '../../../api/client'
import AppIcon from '../../../components/AppIcon.vue'
import { aimApi } from '../api'
import { CA } from '../strings'
import type { AimSessionStatus } from '../types'

const route = useRoute()
const queryClient = useQueryClient()
const sessionId = computed(() => String(route.params.id))

const error = ref<string | null>(null)
const editing = ref<{ participantId: number; value: number } | null>(null)

const monitor = useQuery({
  queryKey: computed(() => ['aim-monitor', sessionId.value]),
  queryFn: () => aimApi.monitor(sessionId.value),
  // Read from the query passed in rather than from `monitor` itself, which
  // would be a reference to the binding being declared.
  refetchInterval: (query) => (query.state.data?.session.status === 'live' ? 2_000 : 15_000),
})

const session = computed(() => monitor.data.value?.session ?? null)
const participants = computed(() => monitor.data.value?.participants ?? [])

function fail(cause: unknown) {
  error.value = cause instanceof ApiError ? cause.message : CA.errors.generic
}

function refresh() {
  void queryClient.invalidateQueries({ queryKey: ['aim-monitor', sessionId.value] })
  void queryClient.invalidateQueries({ queryKey: ['aim-sessions'] })
}

const start = useMutation({
  mutationFn: () => aimApi.startSession(sessionId.value),
  onSuccess: refresh,
  onError: fail,
})
const end = useMutation({
  mutationFn: () => aimApi.endSession(sessionId.value),
  onSuccess: refresh,
  onError: fail,
})
const setBudget = useMutation({
  mutationFn: ({ participantId, value }: { participantId: number; value: number }) =>
    aimApi.setParticipantBudget(sessionId.value, participantId, value),
  onSuccess: () => {
    editing.value = null
    refresh()
  },
  onError: fail,
})

function percent(used: number, budget: number): number {
  if (budget <= 0) return 0
  return Math.min(100, Math.round((used / budget) * 100))
}

/** Gold from three-quarters spent, red once the budget is gone. */
function meterClass(used: number, budget: number): string {
  const share = percent(used, budget)
  if (share >= 100) return 'over'
  if (share >= 75) return 'warn'
  return ''
}

const STATUS_LABEL: Record<AimSessionStatus, string> = {
  waiting: CA.sessions.waiting,
  live: CA.sessions.live,
  ended: CA.sessions.ended,
}
</script>

<template>
  <section>
    <header class="page-head">
      <div>
        <RouterLink class="btn btn-ghost btn-sm" :to="{ name: 'aim-sessions' }">
          <AppIcon name="chevron" :size="14" class="flip" />
          {{ CA.sessions.title }}
        </RouterLink>
        <h1 class="page-title">{{ session?.exercise_title || CA.common.loading }}</h1>
        <p class="page-lead">{{ CA.monitor.lead }}</p>
      </div>
      <div class="head-actions">
        <span v-if="session" class="badge badge-neutral code">
          {{ CA.sessions.code }} {{ session.join_code }}
        </span>
        <span v-if="session" class="badge" :class="session.status === 'live' ? 'badge-olive' : 'badge-gold'">
          {{ STATUS_LABEL[session.status] }}
        </span>
        <button
          v-if="session?.status === 'waiting'"
          class="btn btn-primary"
          type="button"
          :disabled="start.isPending.value"
          @click="start.mutate()"
        >
          <AppIcon name="play" :size="14" />
          {{ CA.sessions.start }}
        </button>
        <button
          v-else-if="session?.status === 'live'"
          class="btn btn-outline"
          type="button"
          :disabled="end.isPending.value"
          @click="end.mutate()"
        >
          {{ CA.sessions.end }}
        </button>
      </div>
    </header>

    <p v-if="error" class="notice-error">{{ error }}</p>

    <div v-if="!participants.length" class="card">
      <div class="card-body"><p class="empty">{{ CA.monitor.empty }}</p></div>
    </div>

    <div v-else class="table-scroll">
      <table class="table">
        <thead>
          <tr>
            <th>{{ CA.monitor.student }}</th>
            <th class="meter-col">{{ CA.monitor.progress }}</th>
            <th class="num">{{ CA.monitor.turns }}</th>
            <th>{{ CA.monitor.lastSaid }}</th>
            <th class="actions-col"></th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="row in participants" :key="row.id">
            <td>
              <span class="who">{{ row.display_name }}</span>
              <span v-if="row.stuck" class="badge badge-gold stuck">{{ CA.monitor.stuck }}</span>
            </td>
            <td>
              <div class="progress" :class="meterClass(row.tokens_used, row.effective_budget)">
                <span :style="{ width: percent(row.tokens_used, row.effective_budget) + '%' }" />
              </div>
              <span class="sub">
                {{ row.tokens_used.toLocaleString('ca') }} /
                {{ row.effective_budget.toLocaleString('ca') }}
                <template v-if="row.context_tokens">
                  · {{ CA.monitor.contextTokens(row.context_tokens) }}
                </template>
              </span>
            </td>
            <td class="num">{{ row.turn_count }}</td>
            <td class="said">
              <span v-if="row.last_message_preview" class="truncate">
                {{ row.last_message_preview }}
              </span>
              <span v-else class="subtle">{{ CA.monitor.noMessages }}</span>
            </td>
            <td class="actions">
              <button
                class="btn btn-ghost btn-sm"
                type="button"
                @click="editing = { participantId: row.id, value: row.effective_budget }"
              >
                {{ CA.monitor.setBudget }}
              </button>
            </td>
          </tr>
        </tbody>
      </table>
    </div>

    <Teleport to="body">
      <div v-if="editing" class="overlay" @click.self="editing = null">
        <div class="dialog" role="dialog" aria-modal="true">
          <h2 class="dialog-title">{{ CA.monitor.setBudget }}</h2>
          <label class="field">
            <span class="label">{{ CA.sessions.tokens }}</span>
            <input v-model.number="editing.value" class="input" type="number" min="0" step="1000" />
          </label>
          <div class="dialog-actions">
            <button class="btn btn-ghost" type="button" @click="editing = null">
              {{ CA.roster.cancel }}
            </button>
            <button
              class="btn btn-primary"
              type="button"
              :disabled="setBudget.isPending.value"
              @click="setBudget.mutate(editing)"
            >
              {{ CA.common.save }}
            </button>
          </div>
        </div>
      </div>
    </Teleport>
  </section>
</template>

<style scoped>
.flip {
  transform: rotate(180deg);
}

.head-actions {
  display: flex;
  align-items: center;
  gap: 8px;
}

.code {
  letter-spacing: 0.08em;
}

.table-scroll {
  margin-top: 12px;
}

.meter-col {
  width: 200px;
}

.who {
  font-weight: 500;
}

.stuck {
  margin-left: 6px;
}

.sub {
  display: block;
  margin-top: 3px;
  font-size: var(--text-xs);
  color: var(--ink-400);
}

.said {
  max-width: 320px;
  color: var(--ink-500);
}

.progress.warn > span {
  background: var(--gold-500);
}

.progress.over > span {
  background: var(--danger-600);
}

.actions-col {
  width: 1%;
}
</style>
