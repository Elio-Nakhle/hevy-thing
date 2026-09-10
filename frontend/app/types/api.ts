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

export type Sex = 'male' | 'female'
export type Units = 'kg' | 'lb'
export type DumbbellLoad = 'per_dumbbell' | 'combined'
export type Goal = 'hypertrophy' | 'strength' | 'powerlifting'

/** Fields of the profile the setup form writes. Keys of `Profile.unset`. */
export type ProfileField =
  | 'sex'
  | 'bodyweight_kg'
  | 'birth_date'
  | 'units'
  | 'dumbbell_load'
  | 'training_goal'

export interface Profile {
  sex: Sex
  /** The bodyweight the analysis uses; a logged measurement outranks the configured one. */
  bodyweight_kg: number
  bodyweight_source: 'measured' | 'configured' | 'default'
  /** What the user typed, which is what the form has to show. */
  configured_bodyweight_kg: number
  birth_date: string | null
  age: number | null
  units: Units
  dumbbell_load: DumbbellLoad
  training_goal: Goal
  training_goal_summary: string
  coach_model: string
  /** Profile fields nobody supplied, so a default is standing in. */
  unset: ProfileField[]
  /** True while something the analysis leans on is still a stand-in. */
  needs_setup: boolean
  /** Absolute path of the .env file a save lands in. */
  env_file: string
}

/** What choosing a training goal changes, from `goals.py`. */
export interface GoalProfile {
  name: Goal
  summary: string
  low_weekly_sets: number | null
  min_heavy_sets_per_week: number | null
  min_main_lift_frequency: number | null
  main_lifts: string[]
  tracks_total: boolean
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

/** A routine and how long it has been waiting. */
export interface RoutineDue {
  title: string
  /** Most recent run, which the prescriptions are computed from. */
  workout_id: string
  last_performed: string
  days_since: number
  runs: number
}

export interface NextSessionExercise {
  template_id: string
  title: string
  muscle_group: string | null
  equipment: string | null
  order: number
  last_top_weight_kg: number | null
  /** Best set at that load. */
  last_top_reps: number | null
  last_top_set_count: number
  /** Every set at the top load. The prescription progresses the worst of them. */
  last_top_set_reps: number[]
  sessions: number
  recommendation: Recommendation
}

export interface NextSession {
  routine: RoutineDue
  exercises: NextSessionExercise[]
  /** Every routine, most overdue first, so the view can switch. */
  alternatives: RoutineDue[]
  changes: string[]
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
  /** Other logged exercises scoring against the same standard, all weaker.
   *  Optional: an older API build does not send it. */
  also_logged?: string[]
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
  bodyweight_source: 'measured' | 'configured' | 'default'
  entries: BenchmarkEntry[]
  unmapped: UnmappedExercise[]
  overall_level_score: number | null
  overall_level: string | null
  /** Reasons to distrust the levels, worst first. Empty when the inputs are real.
   *  Optional: an older API build does not send it. */
  caveats?: string[]
}

/** What the progression model decided to do with an exercise next time. */
export type SessionAction =
  | 'add_load'
  | 'add_reps'
  | 'hold'
  | 'deload'
  | 'establish'
  | 'no_basis'

export interface PerformedSet {
  set_index: number
  set_type: string
  weight_kg: number | null
  reps: number | null
  rpe: number | null
  e1rm_kg: number | null
  volume_kg: number
  /** Set at the exercise's heaviest load. Lighter sets are ramp-up. */
  is_top: boolean
}

export interface Recommendation {
  action: SessionAction
  /** Prose already formatted in the configured unit; prefer the numeric fields. */
  headline: string
  detail: string
  target_sets: number | null
  target_reps: number | null
  target_weight_kg: number | null
  /** [low, high] of the rep range the prescription progresses through. */
  rep_range: [number, number] | null
  load_step_kg: number | null
}

export interface ExercisePrevious {
  workout_id: string
  date: string
  top_weight_kg: number | null
  top_reps: number | null
  top_set_count: number
  volume_kg: number
  best_e1rm_kg: number | null
}

export interface ExerciseBlock {
  template_id: string
  title: string
  muscle_group: string | null
  equipment: string | null
  order: number
  sets: PerformedSet[]
  working_sets: number
  volume_kg: number
  top_weight_kg: number | null
  top_reps: number | null
  best_e1rm_kg: number | null
  sessions: number
  previous: ExercisePrevious | null
  e1rm_delta_kg: number | null
  volume_delta_pct: number | null
  is_pr: boolean
  recommendation: Recommendation
}

export interface RoutineContext {
  title: string
  runs: number
  run_index: number
  previous_id: string | null
  previous_date: string | null
  previous_volume_kg: number | null
  volume_delta_pct: number | null
  median_volume_kg: number | null
}

export interface WorkoutSummary {
  id: string
  title: string
  start_time: string
  end_time: string | null
  duration_minutes: number | null
  exercises: number
  sets: number
  volume_kg: number
  routine_runs: number
  routine_index: number
}

export interface SessionMuscleVolume {
  muscle_group: string
  sets: number
  volume_kg: number
}

export interface WorkoutDetail {
  id: string
  title: string
  start_time: string
  end_time: string | null
  duration_minutes: number | null
  sets: number
  volume_kg: number
  total_reps: number
  routine: RoutineContext
  exercises: ExerciseBlock[]
  muscle_groups: SessionMuscleVolume[]
  notes: string[]
}
