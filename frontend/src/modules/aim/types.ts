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

// ── Exercises ───────────────────────────────────────────────────────────────
export type AimExerciseStatus = 'draft' | 'published' | 'archived'

export interface AimTopic {
  slug: string
  label: string
}

export interface AimDifficultyStep {
  step: number
  label: string
  prompt: string
  escalation: string
}

export interface AimAnticipatedIssue {
  issue: string
  signal: string
  hint: string
}

export interface AimRefined {
  title: string
  statement_md: string
  difficulty_ladder: AimDifficultyStep[]
  anticipated_issues: AimAnticipatedIssue[]
  suggested_topics: string[]
  suggested_level: string
  plot_requests: string[]
}

/** The wizard's steps, as stored. Free text — the model does the shaping. */
export interface AimRawBlocks {
  title?: string
  statement?: string
  difficulty?: string
  issues?: string
  plots?: string
  notes?: string
}

export interface AimVersion {
  id: number
  version: number
  raw_blocks: AimRawBlocks
  refined: AimRefined | null
  plots: AimPlotSpec[]
}

export interface AimExerciseSummary {
  id: number
  title: string
  status: AimExerciseStatus
  topics: string[]
  level: string
  owner_id: number
  owner_name: string
  refined: boolean
  version: number
  updated_at: string
}

export interface AimExerciseDetail extends AimExerciseSummary {
  current: AimVersion | null
}

export interface AimUsage {
  input_tokens: number | null
  output_tokens: number | null
  total_tokens: number | null
}

// ── Plots ───────────────────────────────────────────────────────────────────
export interface AimFunctionPlot {
  kind: 'function'
  title: string
  x_label: string
  y_label: string
  x_min: number
  x_max: number
  grid: boolean
  series: { expression: string; label: string }[]
  markers: { x: number; y: number; label: string }[] | null
}

export interface AimPointsPlot {
  kind: 'points'
  title: string
  x_label: string
  y_label: string
  series: { label: string; mode: 'line' | 'scatter'; points: [number, number][] }[]
}

export interface AimBarsPlot {
  kind: 'bars'
  title: string
  x_label: string
  y_label: string
  categories: string[]
  series: { label: string; values: number[] }[]
}

export interface AimGeometryPlot {
  kind: 'geometry'
  title: string
  shapes: { type: 'segment' | 'circle' | 'polygon' | 'label'; coords: number[]; label: string }[]
}

export type AimPlotSpec = AimFunctionPlot | AimPointsPlot | AimBarsPlot | AimGeometryPlot
