<script setup lang="ts">
import { useMutation, useQuery, useQueryClient } from '@tanstack/vue-query'
import { ref } from 'vue'
import { useRouter } from 'vue-router'

import { ApiError } from '../../../api/client'
import AppIcon from '../../../components/AppIcon.vue'
import { aimApi } from '../api'
import { CA } from '../strings'
import type { AimExerciseSummary } from '../types'

const router = useRouter()
const queryClient = useQueryClient()

const exercises = useQuery({
  queryKey: ['aim-exercises', 'mine'],
  queryFn: () => aimApi.exercises({ scope: 'mine' }),
})

const error = ref<string | null>(null)
const creating = ref(false)
const newTitle = ref('')
const pendingRemoval = ref<AimExerciseSummary | null>(null)

function fail(cause: unknown) {
  error.value = cause instanceof ApiError ? cause.message : CA.errors.generic
}

const create = useMutation({
  mutationFn: (title: string) => aimApi.createExercise(title),
  onSuccess: (exercise) => {
    creating.value = false
    newTitle.value = ''
    void router.push({ name: 'aim-wizard', params: { id: exercise.id } })
  },
  onError: fail,
})

const remove = useMutation({
  mutationFn: (id: number) => aimApi.deleteExercise(id),
  onSuccess: () => {
    error.value = null
    pendingRemoval.value = null
    void queryClient.invalidateQueries({ queryKey: ['aim-exercises'] })
  },
  onError: (cause) => {
    pendingRemoval.value = null
    fail(cause)
  },
})
</script>

<template>
  <section>
    <header class="page-head">
      <div>
        <h1 class="page-title">{{ CA.exercises.title }}</h1>
        <p class="page-lead">{{ CA.exercises.lead }}</p>
      </div>
      <button class="btn btn-primary" type="button" @click="creating = true">
        <AppIcon name="plus" :size="15" />
        {{ CA.exercises.create }}
      </button>
    </header>

    <p v-if="error" class="notice-error">{{ error }}</p>

    <p v-if="exercises.isPending.value" class="muted">{{ CA.common.loading }}</p>
    <div v-else-if="!exercises.data.value?.length" class="card">
      <div class="card-body">
        <p class="empty">{{ CA.exercises.empty }}</p>
      </div>
    </div>

    <ul v-else class="grid">
      <li v-for="item in exercises.data.value" :key="item.id" class="card entry">
        <div class="card-body">
          <div class="entry-head">
            <h2 class="entry-title truncate">{{ item.title }}</h2>
            <span
              class="badge"
              :class="item.status === 'published' ? 'badge-olive' : 'badge-neutral'"
            >
              {{ item.status === 'published' ? CA.exercises.published : CA.exercises.draft }}
            </span>
          </div>

          <p class="entry-meta">
            <span v-if="item.level">{{ item.level }}</span>
            <span v-if="!item.refined" class="warn">{{ CA.exercises.needsRefine }}</span>
          </p>

          <ul v-if="item.topics.length" class="topics">
            <li v-for="topic in item.topics" :key="topic" class="badge badge-neutral">
              {{ topic }}
            </li>
          </ul>

          <div class="actions">
            <button
              class="btn btn-outline btn-sm"
              type="button"
              @click="router.push({ name: 'aim-wizard', params: { id: item.id } })"
            >
              {{ CA.exercises.open }}
            </button>
            <button
              class="btn btn-ghost btn-icon"
              type="button"
              :title="CA.exercises.remove"
              @click="pendingRemoval = item"
            >
              <AppIcon name="trash" />
              <span class="sr-only">{{ CA.exercises.remove }}</span>
            </button>
          </div>
        </div>
      </li>
    </ul>

    <Teleport to="body">
      <div v-if="creating" class="overlay" @click.self="creating = false">
        <form class="dialog" @submit.prevent="create.mutate(newTitle)">
          <h2 class="dialog-title">{{ CA.exercises.createTitle }}</h2>
          <label class="field">
            <input
              v-model="newTitle"
              class="input"
              type="text"
              :placeholder="CA.exercises.createPlaceholder"
              required
              autofocus
            />
          </label>
          <div class="dialog-actions">
            <button class="btn btn-ghost" type="button" @click="creating = false">
              {{ CA.roster.cancel }}
            </button>
            <button
              class="btn btn-primary"
              type="submit"
              :disabled="create.isPending.value || !newTitle.trim()"
            >
              {{ CA.exercises.create }}
            </button>
          </div>
        </form>
      </div>

      <div v-if="pendingRemoval" class="overlay" @click.self="pendingRemoval = null">
        <div class="dialog" role="dialog" aria-modal="true">
          <h2 class="dialog-title">{{ CA.exercises.removeTitle }}</h2>
          <p class="muted">{{ CA.exercises.removeBody(pendingRemoval.title) }}</p>
          <div class="dialog-actions">
            <button class="btn btn-ghost" type="button" @click="pendingRemoval = null">
              {{ CA.roster.cancel }}
            </button>
            <button
              class="btn btn-danger"
              type="button"
              :disabled="remove.isPending.value"
              @click="remove.mutate(pendingRemoval.id)"
            >
              {{ CA.exercises.remove }}
            </button>
          </div>
        </div>
      </div>
    </Teleport>
  </section>
</template>

<style scoped>
.grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(260px, 1fr));
  gap: 10px;
  margin: 14px 0 0;
  padding: 0;
  list-style: none;
}

.entry .card-body {
  display: grid;
  gap: 8px;
  align-content: start;
  height: 100%;
}

.entry-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 8px;
}

.entry-title {
  font-size: var(--text-md);
  min-width: 0;
}

.entry-meta {
  display: flex;
  gap: 8px;
  font-size: var(--text-sm);
  color: var(--ink-400);
}

.entry-meta .warn {
  color: var(--gold-800);
}

.topics {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
  margin: 0;
  padding: 0;
  list-style: none;
}

.actions {
  display: flex;
  gap: 6px;
  margin-top: auto;
  padding-top: 4px;
}
</style>
