/**
 * AIM's slice of the hub API.
 *
 * Its own object rather than additions to the shared `api` const, so the module
 * stays liftable: everything AIM talks to is in this file, and the only thing
 * it borrows from the hub client is transport.
 */
import { request } from '../../api/client'
import type {
  AimCandidate,
  AimExerciseDetail,
  AimExerciseSummary,
  AimIdentity,
  AimMember,
  AimRawBlocks,
  AimRole,
  AimMonitor,
  AimParticipant,
  AimSession,
  AimStudentState,
  AimTopic,
  AimUsage,
  AimVersion,
} from './types'

export interface AimLibraryQuery {
  scope: 'mine' | 'library'
  topic?: string
  level?: string
  q?: string
}

export const aimApi = {
  // ── Roster ────────────────────────────────────────────────────────────────
  identity() {
    return request<AimIdentity>('/aim/me')
  },
  members() {
    return request<AimMember[]>('/aim/members')
  },
  candidates() {
    return request<AimCandidate[]>('/aim/roster/candidates')
  },
  setRole(userId: number, role: AimRole) {
    return request<AimMember>(`/aim/members/${userId}`, {
      method: 'PUT',
      body: JSON.stringify({ role }),
    })
  },
  removeMember(userId: number) {
    return request<void>(`/aim/members/${userId}`, { method: 'DELETE' })
  },

  // ── Exercises ─────────────────────────────────────────────────────────────
  topics() {
    return request<AimTopic[]>('/aim/topics')
  },
  exercises(query: AimLibraryQuery) {
    const params = new URLSearchParams({ scope: query.scope })
    if (query.topic) params.set('topic', query.topic)
    if (query.level) params.set('level', query.level)
    if (query.q) params.set('q', query.q)
    return request<AimExerciseSummary[]>(`/aim/exercises?${params}`)
  },
  exercise(id: number) {
    return request<AimExerciseDetail>(`/aim/exercises/${id}`)
  },
  createExercise(title: string) {
    return request<AimExerciseDetail>('/aim/exercises', {
      method: 'POST',
      body: JSON.stringify({ title }),
    })
  },
  updateExercise(id: number, patch: { title?: string; topics?: string[]; level?: string }) {
    return request<AimExerciseDetail>(`/aim/exercises/${id}`, {
      method: 'PATCH',
      body: JSON.stringify(patch),
    })
  },
  saveDraft(id: number, rawBlocks: AimRawBlocks) {
    return request<AimVersion>(`/aim/exercises/${id}/draft`, {
      method: 'PUT',
      body: JSON.stringify({ raw_blocks: rawBlocks }),
    })
  },
  refine(id: number, rawBlocks: AimRawBlocks, focus?: string) {
    return request<{ version: AimVersion; usage: AimUsage }>(`/aim/exercises/${id}/refine`, {
      method: 'POST',
      body: JSON.stringify({ raw_blocks: rawBlocks, focus: focus || null }),
    })
  },
  generatePlots(id: number, requests: string[]) {
    return request<{ version: AimVersion; usage: AimUsage }>(`/aim/exercises/${id}/plots`, {
      method: 'POST',
      body: JSON.stringify({ requests }),
    })
  },
  publish(id: number, topics: string[], level: string) {
    return request<AimExerciseDetail>(`/aim/exercises/${id}/publish`, {
      method: 'POST',
      body: JSON.stringify({ topics, level }),
    })
  },
  clone(id: number) {
    return request<AimExerciseDetail>(`/aim/exercises/${id}/clone`, { method: 'POST' })
  },
  deleteExercise(id: number) {
    return request<void>(`/aim/exercises/${id}`, { method: 'DELETE' })
  },

  // ── Sessions ──────────────────────────────────────────────────────────────
  sessions() {
    return request<AimSession[]>('/aim/sessions')
  },
  createSession(exerciseId: number, tokenBudget?: number) {
    return request<AimSession>('/aim/sessions', {
      method: 'POST',
      body: JSON.stringify({ exercise_id: exerciseId, token_budget: tokenBudget ?? null }),
    })
  },
  startSession(id: string) {
    return request<AimSession>(`/aim/sessions/${id}/start`, { method: 'POST' })
  },
  endSession(id: string) {
    return request<AimSession>(`/aim/sessions/${id}/end`, { method: 'POST' })
  },
  monitor(id: string) {
    return request<AimMonitor>(`/aim/sessions/${id}/monitor`)
  },
  setParticipantBudget(sessionId: string, participantId: number, budget: number) {
    return request<AimParticipant>(`/aim/sessions/${sessionId}/participants/${participantId}`, {
      method: 'PATCH',
      body: JSON.stringify({ token_budget_override: budget }),
    })
  },

  // ── Student ───────────────────────────────────────────────────────────────
  studentState() {
    return request<AimStudentState>('/aim/student/current')
  },
  join(code: string) {
    return request<AimStudentState>('/aim/sessions/join', {
      method: 'POST',
      body: JSON.stringify({ code }),
    })
  },
}
