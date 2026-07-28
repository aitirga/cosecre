/**
 * AIM's slice of the hub API.
 *
 * Its own object rather than additions to the shared `api` const, so the module
 * stays liftable: everything AIM talks to is in this file, and the only thing
 * it borrows from the hub client is transport.
 */
import { request } from '../../api/client'
import type { AimCandidate, AimIdentity, AimMember, AimRole } from './types'

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
}
