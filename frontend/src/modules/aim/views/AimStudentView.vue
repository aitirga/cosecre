<script setup lang="ts">
/**
 * The student surface.
 *
 * A root route, mounted outside `AppShell`, so there is no hub sidebar: a
 * student has one thing to do here and no other screens to reach. That is also
 * what makes the red theme a scope rather than an override — everything below
 * `.aim-student` re-points the shared tokens, and nothing above it changes.
 *
 * One route, four states, driven by a poll. The state carries the budget too,
 * so the progress bar needs no request of its own.
 */
import { useMutation, useQuery } from '@tanstack/vue-query'
import { computed, ref } from 'vue'
import { RouterLink } from 'vue-router'

import { ApiError } from '../../../api/client'
import BrandMark from '../../../components/BrandMark.vue'
import { useAuth } from '../../../composables/useAuth'
import { aimApi } from '../api'
import AimPlotCard from '../plot/AimPlotCard.vue'
import { CA } from '../strings'
import '../aim.css'

const auth = useAuth()
const code = ref('')
const error = ref<string | null>(null)

const state = useQuery({
  queryKey: ['aim-student-state'],
  queryFn: aimApi.studentState,
  // Five seconds: the only thing being waited for is a teacher pressing a
  // button, and a student staring at a waiting room will forgive that.
  refetchInterval: 5_000,
})

const join = useMutation({
  mutationFn: () => aimApi.join(code.value.trim()),
  onSuccess: () => {
    error.value = null
    code.value = ''
    void state.refetch()
  },
  onError: (cause) => {
    error.value = cause instanceof ApiError ? cause.message : CA.errors.generic
  },
})

const status = computed(() => state.data.value?.state ?? 'idle')
const exercise = computed(() => state.data.value?.exercise ?? null)
</script>

<template>
  <div class="aim-student">
    <header class="bar">
      <BrandMark :size="20" />
      <span class="bar-name">AIM</span>
      <span class="bar-spacer" />
      <span class="who truncate">
        {{ auth.user.value?.display_name || auth.user.value?.email }}
      </span>
    </header>

    <main class="stage" :class="{ working: status === 'live' }">
      <!-- Waiting, idle and ended are the same card with different words. -->
      <div v-if="status !== 'live'" class="card waiting">
        <div class="card-body">
          <span v-if="status === 'waiting'" class="badge badge-accent">
            <span class="badge-dot badge-dot-pulse" />
            {{ CA.student.waitingTag }}
          </span>
          <h1 class="waiting-title">
            {{
              status === 'waiting'
                ? CA.student.waitingTitle
                : status === 'ended'
                  ? CA.student.endedTitle
                  : CA.student.idleTitle
            }}
          </h1>
          <p class="waiting-lead">
            {{
              status === 'waiting'
                ? CA.student.waitingLead
                : status === 'ended'
                  ? CA.student.endedLead
                  : CA.student.idleLead
            }}
          </p>

          <form v-if="status === 'idle'" class="joiner" @submit.prevent="join.mutate()">
            <label class="field">
              <span class="label">{{ CA.student.joinCode }}</span>
              <input v-model="code" class="input input-mono" type="text" maxlength="8" />
            </label>
            <button class="btn btn-primary" type="submit" :disabled="!code.trim()">
              {{ CA.student.join }}
            </button>
          </form>

          <p v-if="error" class="notice-error">{{ error }}</p>
        </div>
      </div>

      <!-- Live: the problem, plainly. The chat lands beside it next. -->
      <article v-else-if="exercise" class="card sheet">
        <div class="card-head">
          <h1 class="card-title">{{ exercise.title }}</h1>
        </div>
        <div class="card-body">
          <p class="statement">{{ exercise.statement_md }}</p>
          <AimPlotCard v-for="(spec, index) in exercise.plots" :key="index" :spec="spec" />
        </div>
      </article>

      <RouterLink class="escape" :to="{ name: 'account' }">{{ CA.student.account }}</RouterLink>
    </main>
  </div>
</template>

<style scoped>
.bar {
  display: flex;
  align-items: center;
  gap: 8px;
  height: var(--topbar-h);
  padding: 0 16px;
  background: var(--surface-0);
  border-bottom: 1px solid var(--line);
}

.bar-name {
  font-size: var(--text-lg);
  font-weight: 650;
  letter-spacing: -0.02em;
}

.bar-spacer {
  flex: 1;
}

.who {
  font-size: var(--text-sm);
  color: var(--ink-400);
  max-width: 40vw;
}

.stage {
  display: grid;
  justify-items: center;
  gap: 14px;
  padding: 12vh 16px 40px;
}

/* Once there is work on screen it belongs at the top, not floating mid-page. */
.stage.working {
  padding-top: 20px;
}

.waiting {
  width: min(520px, 100%);
  text-align: center;
}

.waiting .card-body {
  display: grid;
  justify-items: center;
  gap: 10px;
  padding: 28px 24px;
}

.waiting-title {
  font-size: var(--text-xl);
}

.waiting-lead {
  font-size: var(--text-md);
  color: var(--ink-500);
  max-width: 38ch;
}

.joiner {
  display: grid;
  gap: 8px;
  justify-items: center;
  margin-top: 6px;
}

.joiner .input {
  text-align: center;
  letter-spacing: 0.16em;
  text-transform: uppercase;
}

.sheet {
  width: min(720px, 100%);
}

.sheet .card-body {
  display: grid;
  gap: 14px;
}

.statement {
  font-size: var(--text-md);
  line-height: 1.6;
  color: var(--ink-900);
  white-space: pre-wrap;
}

.escape {
  font-size: var(--text-sm);
  color: var(--ink-400);
}

.escape:hover {
  color: var(--accent-700);
}
</style>
