<script setup lang="ts">
/**
 * The institute's shared exercises.
 *
 * "Shared" needs no registry service: a hub is an institute, so the library is
 * simply every published exercise on this server.
 */
import { useMutation, useQuery, useQueryClient } from '@tanstack/vue-query'
import { computed, ref } from 'vue'
import { useRouter } from 'vue-router'

import { ApiError } from '../../../api/client'
import AppIcon from '../../../components/AppIcon.vue'
import { aimApi } from '../api'
import { CA } from '../strings'

const router = useRouter()
const queryClient = useQueryClient()

const topic = ref('')
const search = ref('')
const error = ref<string | null>(null)
const notice = ref<string | null>(null)

const topics = useQuery({ queryKey: ['aim-topics'], queryFn: aimApi.topics })
const exercises = useQuery({
  queryKey: computed(() => ['aim-exercises', 'library', topic.value, search.value]),
  queryFn: () =>
    aimApi.exercises({ scope: 'library', topic: topic.value || undefined, q: search.value || undefined }),
})

const clone = useMutation({
  mutationFn: (id: number) => aimApi.clone(id),
  onSuccess: (created) => {
    error.value = null
    notice.value = CA.library.cloned
    void queryClient.invalidateQueries({ queryKey: ['aim-exercises'] })
    void router.push({ name: 'aim-wizard', params: { id: created.id } })
  },
  onError: (cause) => {
    error.value = cause instanceof ApiError ? cause.message : CA.errors.generic
  },
})

const labelFor = (slug: string) =>
  topics.data.value?.find((item) => item.slug === slug)?.label ?? slug
</script>

<template>
  <section>
    <header class="page-head">
      <div>
        <h1 class="page-title">{{ CA.library.title }}</h1>
        <p class="page-lead">{{ CA.library.lead }}</p>
      </div>
    </header>

    <div class="filters">
      <input v-model="search" class="input" type="search" :placeholder="CA.library.search" />
      <select v-model="topic" class="select">
        <option value="">{{ CA.library.allTopics }}</option>
        <option v-for="item in topics.data.value" :key="item.slug" :value="item.slug">
          {{ item.label }}
        </option>
      </select>
    </div>

    <p v-if="error" class="notice-error">{{ error }}</p>
    <p v-else-if="notice" class="notice-success">{{ notice }}</p>

    <p v-if="exercises.isPending.value" class="muted">{{ CA.common.loading }}</p>
    <div v-else-if="!exercises.data.value?.length" class="card">
      <div class="card-body"><p class="empty">{{ CA.library.empty }}</p></div>
    </div>

    <ul v-else class="grid">
      <li v-for="item in exercises.data.value" :key="item.id" class="card entry">
        <div class="card-body">
          <h2 class="entry-title truncate">{{ item.title }}</h2>
          <p class="entry-meta">
            <span>{{ CA.exercises.by(item.owner_name) }}</span>
            <span v-if="item.level">{{ item.level }}</span>
          </p>
          <ul v-if="item.topics.length" class="topics">
            <li v-for="slug in item.topics" :key="slug" class="badge badge-neutral">
              {{ labelFor(slug) }}
            </li>
          </ul>
          <button
            class="btn btn-outline btn-sm"
            type="button"
            :disabled="clone.isPending.value"
            @click="clone.mutate(item.id)"
          >
            <AppIcon name="download" :size="14" />
            {{ CA.library.clone }}
          </button>
        </div>
      </li>
    </ul>
  </section>
</template>

<style scoped>
.filters {
  display: flex;
  gap: 8px;
  margin-top: 12px;
}

/* The select has an intrinsic width that wins a `flex: 1` fight, so the search
   box is the one that grows and the select is pinned. */
.filters .input {
  flex: 1 1 auto;
  min-width: 0;
}

.filters .select {
  flex: 0 0 200px;
}

.grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(260px, 1fr));
  gap: 10px;
  margin: 12px 0 0;
  padding: 0;
  list-style: none;
}

.entry .card-body {
  display: grid;
  gap: 8px;
  align-content: start;
  height: 100%;
}

.entry-title {
  font-size: var(--text-md);
}

.entry-meta {
  display: flex;
  gap: 8px;
  font-size: var(--text-sm);
  color: var(--ink-400);
}

.topics {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
  margin: 0;
  padding: 0;
  list-style: none;
}

.entry .btn {
  margin-top: auto;
  justify-self: start;
}
</style>
