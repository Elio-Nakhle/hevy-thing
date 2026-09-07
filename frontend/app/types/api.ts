/**
 * Response shapes for the backend API.
 *
 * These mirror the dataclasses in `backend/src/hevy_coach/`. They are written by
 * hand rather than generated because `/api/**` is a dev-server proxy to FastAPI,
 * so Nuxt has no schema to infer from and types every response as `{}` - which
 * silently disables typechecking across every page. Passing these as `useFetch`
 * generics turns it back on.
 *
 * Every weight is in kilograms. Display conversion belongs to `useUnits`.
 */

export type Level = 'beginner' | 'novice' | 'intermediate' | 'advanced' | 'elite'
export type Trend = 'progressing' | 'maintaining' | 'stalling' | 'regressing'
export type Severity = 'info' | 'suggestion' | 'warning'

export interface Health {
  status: string
  workouts: number
  last_workout: string | null
  last_import: string | null
  imported_file: string | null
  /** Name of the export the next import would read, or null if the folder is empty. */
  available_export: string | null
}

export interface Profile {
  sex: 'male' | 'female'
  bodyweight_kg: number
  bodyweight_source: 'measured' | 'configured'
  age: number | null
  units: 'kg' | 'lb'
  coach_model: string
}

export interface ImportResult {
  file: string
  workouts: number
  sets: number
  exercises: number
  workouts_removed: number
  /** Exercise titles with no muscle mapping; they count as "other". */
  unmapped: string[]
  errors: string[]
  summary: string
}

export interface Overview {
  workouts: number
  first_workout: string | null
  last_workout: string | null
  total_sets: number
  total_reps: number
  total_volume_kg: number
  avg_workouts_per_week: number
  avg_duration_minutes: number | null
  distinct_exercises: number
  bodyweight_kg: number | null
}

export interface WeeklyVolume {
  week: string
  week_start: string
  sets: number
  reps: number
  volume_kg: number
  workouts: number
}

export interface MuscleVolume {
  muscle_group: string
  sets: number
  sets_per_week: number
  volume_kg: number
}

export interface ExerciseSummary {
  template_id: string
  title: string
  sessions: number
  sets: number
  last_performed: string | null
  best_e1rm_kg: number | null
  best_weight_kg: number | null
  total_volume_kg: number
}

export interface SessionPoint {
  date: string
  workout_id: string
  best_e1rm_kg: number | null
  best_weight_kg: number | null
  top_set_reps: number | null
  sets: number
  volume_kg: number
}

export interface PersonalRecord {
  template_id: string
  title: string
  date: string
  weight_kg: number
  reps: number
  e1rm_kg: number
  is_current_best: boolean
}

export interface ExerciseTrend {
  template_id: string
  title: string
  sessions: number
  first_date: string
  last_date: string
  days_since_last: number
  first_e1rm_kg: number
  latest_e1rm_kg: number
  best_e1rm_kg: number
  slope_kg_per_month: number
  change_pct_per_month: number
  trend: Trend
  sessions_since_best: number
  lift: string | null
  level: string | null
  level_score: number | null
  kg_to_next_level: number | null
}

export interface Insight {
  kind: string
  severity: Severity
  title: string
  detail: string
  evidence: Record<string, unknown>
}

export interface LiftScore {
  lift: string
  name: string
  /** "kg" for absolute load, "added_kg" for load added to bodyweight. */
  metric: 'kg' | 'added_kg'
  e1rm_kg: number
  bodyweight_kg: number
  level: string
  /** 0 = beginner, 2 = intermediate, 4 = elite; outside that range at the ends. */
  level_score: number
  percentile_estimate: number
  thresholds: Record<Level, number>
  next_level: string | null
  kg_to_next_level: number | null
  ratio: number
  source: string
  notes: string[]
}

export interface BenchmarkEntry {
  template_id: string
  title: string
  lift: string
  last_performed: string | null
  sessions: number
  score: LiftScore
}

export interface UnmappedExercise {
  template_id: string
  title: string
  sessions: number
  best_e1rm_kg?: number | null
  reason?: string
}

export interface BenchmarkReport {
  sex: string
  bodyweight_kg: number
  age: number | null
  bodyweight_source: 'measured' | 'configured'
  entries: BenchmarkEntry[]
  unmapped: UnmappedExercise[]
  overall_level_score: number | null
  overall_level: string | null
}
