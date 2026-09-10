<script setup lang="ts">
/**
 * The rack view: what to do in your next session, on a phone.
 *
 * The prescriptions themselves are not new - `session.py` has computed them
 * since the beginning, buried at the bottom of a workout-detail page you could
 * only reach on a laptop, after training. Every participant in the roadmap's
 * research rated them the most useful thing in the app and none of them could
 * get to them at the point of use.
 *
 * So this page is deliberately thin: one column, big type, no charts, read-only.
 * It also states each prescription's reasoning inline rather than in a tooltip,
 * because native tooltips do not open on touch.
 */
import { computed, ref } from 'vue'
import type { NextSession, NextSessionExercise, Recommendation, SessionAction } from '~/types/api'
import { fullDate, titleCase } from '~/utils/format'

const { weight } = useUnits()

/** Which routine to show. Empty means "whichever is due". */
const routine = ref('')

const { data: session, pending, error } = await useFetch<NextSession>('/api/next-session', {
  query: computed(() => (routine.value ? { routine: routine.value } : {})),
})

/** How each action reads at a glance. Colour carries "is this a push or a
 *  back-off", which is the only distinction that matters mid-session. */
const ACTIONS: Record<SessionAction, { label: string; colour: string }> = {
  add_load: { label: 'Add weight', colour: 'var(--good)' },
  add_reps: { label: 'Add reps', colour: 'var(--series-1)' },
  hold: { label: 'Repeat', colour: 'var(--text-muted)' },
  deload: { label: 'Back off', colour: 'var(--warning)' },
  establish: { label: 'Baseline', colour: 'var(--text-muted)' },
  no_basis: { label: 'No target', colour: 'var(--text-muted)' },
}

function action(item: Recommendation) {
  return ACTIONS[item.action] ?? ACTIONS.no_basis
}

/** Built from the numeric fields rather than `headline`, so a lifter who reads
 *  in pounds gets pounds. */
function prescription(item: Recommendation): string {
  if (item.target_sets === null || item.target_reps === null) return item.headline
  const load = item.target_weight_kg ? weight(item.target_weight_kg) : 'bodyweight'
  return `${item.target_sets} × ${item.target_reps} @ ${load}`
}

/**
 * What you actually did, set by set.
 *
 * Every set rather than the best one: the prescription progresses the *worst*
 * set at the top load, so "2 × 12" beside a target of 11 reads as a downgrade
 * when the truth was a 12 and a 10.
 */
function lastTime(exercise: NextSessionExercise): string | null {
  const reps = exercise.last_top_set_reps
  if (reps.length === 0) return null
  const load = exercise.last_top_weight_kg ? weight(exercise.last_top_weight_kg) : 'bodyweight'
  const uniform = reps.every((count) => count === reps[0])
  const scheme = uniform ? `${reps.length} × ${reps[0]}` : reps.join(', ')
  return `${scheme} @ ${load}`
}

/** The weight change from last time, when there is one worth showing. */
function loadDelta(exercise: NextSessionExercise): string | null {
  const target = exercise.recommendation.target_weight_kg
  const last = exercise.last_top_weight_kg
  if (target === null || last === null || Math.abs(target - last) < 0.01) return null
  const sign = target > last ? '+' : '−'
  return `${sign}${weight(Math.abs(target - last))}`
}

function routineLabel(title: string): string {
  return title.trim() || 'Untitled'
}

function daysAgo(days: number): string {
  if (days === 0) return 'today'
  if (days === 1) return 'yesterday'
  return `${days} days ago`
}
</script>

<template>
  <div class="rack">
    <div v-if="error" class="card empty">
      <h1>Nothing to prescribe yet</h1>
      <p class="secondary">
        Import a Hevy CSV export on the <NuxtLink to="/">dashboard</NuxtLink> and this fills
        in with your next session.
      </p>
    </div>

    <template v-else-if="session">
      <header class="head">
        <span class="eyebrow secondary">Next session</span>
        <h1>{{ routineLabel(session.routine.title) }}</h1>
        <p class="sub secondary">
          Last run {{ daysAgo(session.routine.days_since) }}
          ({{ fullDate(session.routine.last_performed) }}) &middot;
          run {{ session.routine.runs }} of this routine
        </p>
      </header>

      <div v-if="session.alternatives.length > 1" class="switcher">
        <button
          v-for="option in session.alternatives"
          :key="option.title"
          type="button"
          class="chip"
          :aria-pressed="option.title === session.routine.title"
          @click="routine = option.title"
        >
          {{ routineLabel(option.title) }}
          <span class="chip-days">{{ option.days_since }}d</span>
        </button>
      </div>

      <p class="summary" :class="{ stale: pending }">{{ session.summary }}</p>

      <ol class="list" :class="{ stale: pending }">
        <li v-for="exercise in session.exercises" :key="exercise.template_id" class="card item">
          <div class="item-head">
            <h2>{{ exercise.title }}</h2>
            <span
              class="tag"
              :style="{ background: action(exercise.recommendation).colour }"
            >{{ action(exercise.recommendation).label }}</span>
          </div>

          <p v-if="exercise.muscle_group" class="muscle muted">
            {{ titleCase(exercise.muscle_group) }}
          </p>

          <p class="target">
            {{ prescription(exercise.recommendation) }}
            <span v-if="loadDelta(exercise)" class="delta">{{ loadDelta(exercise) }}</span>
          </p>

          <p v-if="lastTime(exercise)" class="last secondary">
            Last time: {{ lastTime(exercise) }}
          </p>

          <p class="why muted">{{ exercise.recommendation.detail }}</p>
        </li>
      </ol>

      <p class="foot muted">
        Prescriptions use double progression: hold the weight until you reach the top of the
        rep range on every working set, then add the smallest jump this exercise moves in and
        drop back to the bottom. Read-only - nothing here is logged back to Hevy.
      </p>
    </template>
  </div>
</template>

<style scoped>
/* One column, thumb-width, regardless of the screen it lands on. */
.rack {
  max-width: 30rem;
  margin: 0 auto;
}

.head {
  margin-bottom: 16px;
}

.eyebrow {
  font-size: 12px;
  font-weight: 500;
  text-transform: uppercase;
  letter-spacing: 0.06em;
}

.head h1 {
  font-size: 28px;
  margin: 2px 0 0;
}

.sub {
  margin: 4px 0 0;
  font-size: 12px;
}

.switcher {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-bottom: 16px;
}

/* 44px tall: the smallest thing a thumb hits reliably. */
.chip {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  min-height: 44px;
  padding: 0 14px;
  border: 1px solid var(--border);
  border-radius: 999px;
  background: var(--surface-1);
  color: var(--text-secondary);
  font: inherit;
  font-size: 13px;
  cursor: pointer;
}

.chip[aria-pressed='true'] {
  border-color: var(--series-1);
  color: var(--text-primary);
  font-weight: 500;
  background: color-mix(in srgb, var(--series-1) 8%, var(--surface-1));
}

.chip-days {
  font-size: 11px;
  color: var(--text-muted);
  font-variant-numeric: tabular-nums;
}

.summary {
  margin: 0 0 16px;
  font-size: 15px;
  font-weight: 500;
  line-height: 1.4;
}

.list {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.item-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 10px;
}

.item h2 {
  font-size: 16px;
  line-height: 1.3;
}

.tag {
  color: #fff;
  font-size: 11px;
  font-weight: 500;
  padding: 2px 8px;
  border-radius: 999px;
  white-space: nowrap;
  flex: none;
}

.muscle {
  margin: 2px 0 0;
  font-size: 12px;
}

/* The number you are standing there to read. */
.target {
  margin: 12px 0 0;
  font-size: 26px;
  font-weight: 600;
  letter-spacing: -0.02em;
  font-variant-numeric: tabular-nums;
  display: flex;
  align-items: baseline;
  gap: 10px;
  flex-wrap: wrap;
}

.delta {
  font-size: 13px;
  font-weight: 500;
  color: var(--text-secondary);
  letter-spacing: 0;
}

.last {
  margin: 6px 0 0;
  font-size: 13px;
  font-variant-numeric: tabular-nums;
}

.why {
  margin: 10px 0 0;
  font-size: 12px;
  line-height: 1.5;
}

.foot {
  margin: 20px 0 0;
  font-size: 11px;
  line-height: 1.5;
}

.empty {
  text-align: center;
  padding: 40px 24px;
}

.empty p {
  margin: 10px auto 0;
  max-width: 34ch;
  font-size: 13px;
}
</style>
