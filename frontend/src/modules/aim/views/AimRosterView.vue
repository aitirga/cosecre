<script setup lang="ts">
import { useMutation, useQuery, useQueryClient } from '@tanstack/vue-query'
import { computed, ref } from 'vue'

import { ApiError } from '../../../api/client'
import AppIcon from '../../../components/AppIcon.vue'
import { aimApi } from '../api'
import { CA } from '../strings'
import type { AimMember, AimRole } from '../types'

const queryClient = useQueryClient()

const members = useQuery({ queryKey: ['aim-members'], queryFn: aimApi.members })
const candidates = useQuery({ queryKey: ['aim-candidates'], queryFn: aimApi.candidates })

const error = ref<string | null>(null)
const pendingRemoval = ref<AimMember | null>(null)
const adding = ref(false)

/**
 * Accounts are created on the hub's own Team screen, so who *could* be added
 * changes without this view hearing about it. Re-asking as the dialog opens is
 * the difference between "the person I just created is missing" and a list that
 * is simply right.
 */
function openAdd() {
  adding.value = true
  void candidates.refetch()
}

function refresh() {
  void queryClient.invalidateQueries({ queryKey: ['aim-members'] })
  void queryClient.invalidateQueries({ queryKey: ['aim-candidates'] })
}

function fail(cause: unknown) {
  error.value = cause instanceof ApiError ? cause.message : CA.errors.generic
}

const setRole = useMutation({
  mutationFn: ({ userId, role }: { userId: number; role: AimRole }) =>
    aimApi.setRole(userId, role),
  onSuccess: () => {
    error.value = null
    adding.value = false
    refresh()
  },
  onError: fail,
})

const removeMember = useMutation({
  mutationFn: (userId: number) => aimApi.removeMember(userId),
  onSuccess: () => {
    error.value = null
    pendingRemoval.value = null
    refresh()
  },
  onError: (cause) => {
    pendingRemoval.value = null
    fail(cause)
  },
})

const teachers = computed(() => members.data.value?.filter((m) => m.role === 'teacher') ?? [])
const students = computed(() => members.data.value?.filter((m) => m.role === 'student') ?? [])
const busy = computed(() => setRole.isPending.value || removeMember.isPending.value)

function nameOf(member: { display_name: string | null; email: string }) {
  return member.display_name || member.email
}
</script>

<template>
  <section>
    <header class="page-head">
      <div>
        <h1 class="page-title">{{ CA.roster.title }}</h1>
        <p class="page-lead">{{ CA.roster.lead }}</p>
      </div>
      <button class="btn btn-primary" type="button" :disabled="busy" @click="openAdd">
        <AppIcon name="plus" :size="15" />
        {{ CA.roster.addSomeone }}
      </button>
    </header>

    <p v-if="error" class="notice-error">{{ error }}</p>

    <div class="card">
      <div class="card-head">
        <h2 class="card-title">{{ CA.roster.teachers }}</h2>
      </div>
      <div class="card-body">
        <p v-if="members.isPending.value" class="muted">{{ CA.common.loading }}</p>
        <p v-else-if="!teachers.length" class="empty">{{ CA.roster.empty }}</p>
        <ul v-else class="people">
          <li v-for="member in teachers" :key="member.user_id" class="person">
            <span class="person-name truncate">{{ nameOf(member) }}</span>
            <span v-if="member.implicit" class="badge badge-neutral">
              {{ CA.roster.implicit }}
            </span>
            <div class="actions">
              <button
                class="btn btn-ghost btn-sm"
                type="button"
                :disabled="busy"
                @click="setRole.mutate({ userId: member.user_id, role: 'student' })"
              >
                {{ CA.roster.makeStudent }}
              </button>
              <button
                v-if="!member.implicit"
                class="btn btn-ghost btn-icon"
                type="button"
                :title="CA.roster.remove"
                :disabled="busy"
                @click="pendingRemoval = member"
              >
                <AppIcon name="trash" />
                <span class="sr-only">{{ CA.roster.remove }}</span>
              </button>
            </div>
          </li>
        </ul>
      </div>
    </div>

    <div class="card">
      <div class="card-head">
        <h2 class="card-title">{{ CA.roster.students }}</h2>
      </div>
      <div class="card-body">
        <p v-if="members.isPending.value" class="muted">{{ CA.common.loading }}</p>
        <p v-else-if="!students.length" class="empty">{{ CA.roster.empty }}</p>
        <ul v-else class="people">
          <li v-for="member in students" :key="member.user_id" class="person">
            <span class="person-name truncate">{{ nameOf(member) }}</span>
            <div class="actions">
              <button
                class="btn btn-ghost btn-sm"
                type="button"
                :disabled="busy"
                @click="setRole.mutate({ userId: member.user_id, role: 'teacher' })"
              >
                {{ CA.roster.makeTeacher }}
              </button>
              <button
                class="btn btn-ghost btn-icon"
                type="button"
                :title="CA.roster.remove"
                :disabled="busy"
                @click="pendingRemoval = member"
              >
                <AppIcon name="trash" />
                <span class="sr-only">{{ CA.roster.remove }}</span>
              </button>
            </div>
          </li>
        </ul>
      </div>
    </div>

    <Teleport to="body">
      <div v-if="adding" class="overlay" @click.self="adding = false">
        <div class="dialog" role="dialog" aria-modal="true">
          <h2 class="dialog-title">{{ CA.roster.addSomeone }}</h2>
          <p v-if="!candidates.data.value?.length" class="empty">
            {{ CA.roster.noCandidates }}
          </p>
          <ul v-else class="people">
            <li v-for="person in candidates.data.value" :key="person.id" class="person">
              <span class="person-name truncate">{{ nameOf(person) }}</span>
              <div class="actions">
                <button
                  class="btn btn-outline btn-sm"
                  type="button"
                  :disabled="busy"
                  @click="setRole.mutate({ userId: person.id, role: 'student' })"
                >
                  {{ CA.roster.roleStudent }}
                </button>
                <button
                  class="btn btn-outline btn-sm"
                  type="button"
                  :disabled="busy"
                  @click="setRole.mutate({ userId: person.id, role: 'teacher' })"
                >
                  {{ CA.roster.roleTeacher }}
                </button>
              </div>
            </li>
          </ul>
          <div class="dialog-actions">
            <button class="btn btn-ghost" type="button" @click="adding = false">
              {{ CA.roster.cancel }}
            </button>
          </div>
        </div>
      </div>

      <div v-if="pendingRemoval" class="overlay" @click.self="pendingRemoval = null">
        <div class="dialog" role="dialog" aria-modal="true">
          <h2 class="dialog-title">{{ CA.roster.removeTitle }}</h2>
          <p class="muted">{{ CA.roster.removeBody(nameOf(pendingRemoval)) }}</p>
          <div class="dialog-actions">
            <button class="btn btn-ghost" type="button" @click="pendingRemoval = null">
              {{ CA.roster.cancel }}
            </button>
            <button
              class="btn btn-danger"
              type="button"
              :disabled="busy"
              @click="removeMember.mutate(pendingRemoval.user_id)"
            >
              {{ CA.roster.remove }}
            </button>
          </div>
        </div>
      </div>
    </Teleport>
  </section>
</template>

<style scoped>
.card + .card {
  margin-top: 14px;
}

.people {
  display: grid;
  gap: 2px;
  margin: 0;
  padding: 0;
  list-style: none;
}

.person {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 7px 8px;
  border-radius: var(--r-md);
}

.person:hover {
  background: var(--surface-2);
}

.person-name {
  flex: 1;
  min-width: 0;
  font-size: var(--text-base);
}
</style>
