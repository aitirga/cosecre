/** AIM's wire types. Mirrors `api/aim/schemas.py`. */

export type AimRole = 'teacher' | 'student'

export interface AimIdentity {
  user_id: number
  /** Null for a hub user with no business in AIM. The module hides itself. */
  role: AimRole | null
  is_hub_admin: boolean
  /** True when the role was inferred from hub admin rather than granted. */
  implicit: boolean
}

export interface AimMember {
  user_id: number
  email: string
  display_name: string | null
  role: AimRole
  implicit: boolean
}

export interface AimCandidate {
  id: number
  email: string
  display_name: string | null
}
