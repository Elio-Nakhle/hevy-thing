<script setup lang="ts">
/**
 * One session: what it did to each lift, and what to load the next time this
 * routine comes round.
 *
 * The plan card is deliberately first and deliberately terse - it is the part
 * you read standing in front of a rack. Everything below it is the evidence for
 * the plan, in the order you would want to argue with it: what you actually
 * did, how it compared to last time, and why the model chose what it chose.
 */
import { computed } from 'vue'
import { useRoute } from 'vue-router'
import type { ExerciseBlock, SessionAction, WorkoutDetail } from '~/types/api'
import { fullDate, titleCase } from '~/utils/format'

const { unit, amount, weight } = useUnits()

const route = useRoute()
const workoutId = computed(() => String(route.params.id))

const { data: detail, error } = await useFetch<WorkoutDetail>(
  () => `/api/workouts/${workoutId.value}`,
)

/** Colour and wording per progression decision. Colour never carries meaning
 *  alone - every chip is labelled, and the reasoning sits beside it. */
const ACTIONS: Record<SessionAction, { label: string; color: string }> = {
  add_load: { label: 'Add load', color: 'var(--success-text)' },
  add_reps: { label: 'Add reps', color: 'var(--series-1)' },
  hold: { label: 'Hold', color: 'var(--warning)' },
  deload: { label: 'Deload', color: 'var(--critical)' },
  establish: { label: 'Baseline', color: 'var(--text-secondary)' },
  no_basis: { label: 'Not scored', color: 'var(--text-muted)' },
}

/** "3 x 8 @ 62.5 kg", built from the numeric fields so it honours kg/lb. */
function prescription(block: ExerciseBlock): string {
  const rec = block.recommendation
  if (rec.target_sets === null || rec.target_reps === null) return '-'
  const load = rec.target_weight_kg ? weight(rec.target_weight_kg) : 'bodyweight'
  return `${rec.target_sets} × ${rec.target_reps} @ ${load}`
}

/** What was actually done on the top sets: "2 × 8 @ 25 kg". */
function performed(block: ExerciseBlock): string {
  const top = block.sets.filter((set) => set.is_top)
  if (top.length === 0) return '-'
  const reps = [...new Set(top.map((set) => set.reps))].join('/')
  const load = block.top_weight_kg ? weight(block.top_weight_kg) : 'bodyweight'
  return `${top.length} × ${reps} @ ${load}`
}

function ramp(block: ExerciseBlock): string {
  const up = block.sets.filter((set) => !set.is_top)
  return up.map((set) => `${amount(set.weight_kg, 0)}×${set.reps}`).join(', ')
}

const planned = computed(() =>
  (detail.value?.exercises ?? []).filter((b) => b.recommendation.action !== 'no_basis'),
)

const prs = computed(() => (detail.value?.exercises ?? []).filter((b) => b.is_pr).length)

const maxMuscleSets = computed(() =>
  Math.max(1, ...(detail.value?.muscle_groups ?? []).map((g) => g.sets)),
)
</script>

<template>
  <div>
    <p v-if="error" class="card empty">No session with that id.</p>

    <template v-else-if="detail">
      <div class="page-head">
        <div>
          <NuxtLink to="/workouts" class="back secondary">&larr; Workouts</NuxtLink>
          <h1>{{ detail.title }}</h1>
          <p class="secondary sub">
            {{ fullDate(detail.start_time) }} &middot;
            run {{ detail.routine.run_index }} of {{ detail.routine.runs }}
            <template v-if="detail.routine.runs > 1"> of this routine</template>
            <!-- Run-to-run tonnage swings wildly with which accessories made the
                 cut, so the routine's own median is the steadier reference. -->
            <template v-if="detail.routine.runs > 2 && detail.routine.median_volume_kg">
              &middot; typical run is
              {{ amount(detail.routine.median_volume_kg, 0) }} {{ unit }}
            </template>
          </p>
        </div>
      </div>

      <div class="grid grid-4 tiles">
        <StatTile
          :value="amount(detail.volume_kg, 0)"
          :unit="unit"
          :delta="detail.routine.volume_delta_pct"
          delta-label="vs previous run"
        >
          <template #label><Term id="volume" capitalize /></template>
        </StatTile>
        <StatTile :value="String(detail.sets)">
          <template #label><Term id="working_set" capitalize />s</template>
        </StatTile>
        <StatTile
          label="Duration"
          :value="detail.duration_minutes ? String(Math.round(detail.duration_minutes)) : '-'"
          unit="min"
        />
        <StatTile label="Lifetime bests" :value="String(prs)" />
      </div>

      <section v-if="detail.notes.length" class="card notes">
        <div class="card-head"><h2 class="card-title">Worth knowing</h2></div>
        <ul>
          <li v-for="note in detail.notes" :key="note">{{ note }}</li>
        </ul>
      </section>

      <!-- The plan. First, because it is the reason to open this page. -->
      <section class="card plan">
        <div class="card-head">
          <h2 class="card-title">Next time you run {{ detail.title }}</h2>
        </div>
        <p class="card-sub">
          <Term id="prescription" capitalize />: hold the load until every
          <Term id="working_set" /> reaches the top of its <Term id="rep_range" />, then add
          the <Term id="load_step" /> your history shows you actually use and drop back to
          the bottom of the range. <NuxtLink to="/next">Take it to the rack</NuxtLink>.
        </p>

        <p v-if="planned.length === 0" class="empty">
          Nothing here can be progressed - no session had both a load and a rep count.
        </p>
        <div v-else class="scroll-x">
          <table class="data-table">
            <thead>
              <tr>
                <th>Exercise</th>
                <th>This session</th>
                <th>Next target</th>
                <th>Range</th>
                <th class="left">Call</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="block in planned" :key="block.template_id">
                <td class="left">
                  <NuxtLink :to="`/exercises/${block.template_id}`" class="ex-link">
                    {{ block.title }}
                  </NuxtLink>
                </td>
                <td>{{ performed(block) }}</td>
                <td class="target">{{ prescription(block) }}</td>
                <td class="muted">
                  <template v-if="block.recommendation.rep_range">
                    {{ block.recommendation.rep_range[0] }}-{{ block.recommendation.rep_range[1] }}
                  </template>
                  <span v-else>-</span>
                </td>
                <td class="left">
                  <span class="chip" :style="{ color: ACTIONS[block.recommendation.action].color }">
                    <span
                      class="dot"
                      :style="{ background: ACTIONS[block.recommendation.action].color }"
                    />
                    {{ ACTIONS[block.recommendation.action].label }}
                  </span>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </section>

      <!-- The evidence, exercise by exercise. -->
      <h2 class="section-head">Session detail</h2>
      <section v-for="block in detail.exercises" :key="block.template_id" class="card exercise">
        <div class="ex-head">
          <div>
            <h3>
              <NuxtLink :to="`/exercises/${block.template_id}`" class="ex-link">
                {{ block.title }}
              </NuxtLink>
              <span v-if="block.is_pr" class="pr">best <Term id="e1rm" /></span>
            </h3>
            <p class="secondary meta">
              <template v-if="block.muscle_group">{{ titleCase(block.muscle_group) }} &middot; </template>
              {{ block.working_sets }} sets &middot;
              {{ amount(block.volume_kg, 0) }} {{ unit }} &middot;
              session {{ block.sessions }} on this lift
            </p>
          </div>
          <span class="chip" :style="{ color: ACTIONS[block.recommendation.action].color }">
            <span class="dot" :style="{ background: ACTIONS[block.recommendation.action].color }" />
            {{ ACTIONS[block.recommendation.action].label }}
          </span>
        </div>

        <div class="ex-body">
          <div>
            <table class="data-table">
              <thead>
                <tr>
                  <th>Set</th>
                  <th>Load ({{ unit }})</th>
                  <th>Reps</th>
                  <th><Term id="e1rm" capitalize /> ({{ unit }})</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="set in block.sets" :key="set.set_index" :class="{ ramp: !set.is_top }">
                  <td>
                    {{ set.set_index + 1 }}
                    <span v-if="!set.is_top" class="muted"> <Term id="ramp_up" /></span>
                  </td>
                  <td>
                    <template v-if="set.weight_kg !== null">{{ amount(set.weight_kg) }}</template>
                    <span v-else class="muted">bw</span>
                  </td>
                  <td>{{ set.reps ?? '-' }}</td>
                  <td>{{ set.e1rm_kg !== null ? amount(set.e1rm_kg) : '-' }}</td>
                </tr>
              </tbody>
            </table>
          </div>

          <div class="ex-side">
            <div v-if="block.previous" class="compare">
              <h4>Against {{ fullDate(block.previous.date) }}</h4>
              <dl>
                <div>
                  <dt>Top set</dt>
                  <dd>
                    {{ block.previous.top_set_count }} ×
                    {{ block.previous.top_reps }} @
                    {{ block.previous.top_weight_kg ? weight(block.previous.top_weight_kg) : 'bw' }}
                  </dd>
                </div>
                <div>
                  <dt><Term id="e1rm" capitalize /></dt>
                  <dd :style="{ color: (block.e1rm_delta_kg ?? 0) >= 0 ? 'var(--success-text)' : 'var(--critical)' }">
                    <template v-if="block.e1rm_delta_kg !== null">
                      {{ block.e1rm_delta_kg >= 0 ? '+' : '' }}{{ amount(block.e1rm_delta_kg) }} {{ unit }}
                    </template>
                    <span v-else class="muted">-</span>
                  </dd>
                </div>
                <div>
                  <dt><Term id="volume" capitalize /></dt>
                  <dd>
                    <template v-if="block.volume_delta_pct !== null">
                      {{ block.volume_delta_pct >= 0 ? '+' : '' }}{{ block.volume_delta_pct.toFixed(0) }}%
                    </template>
                    <span v-else class="muted">-</span>
                  </dd>
                </div>
              </dl>
            </div>
            <p v-else class="secondary first-time">First time this exercise appears in the log.</p>

            <div class="rec">
              <h4>Next time</h4>
              <p class="rec-line">{{ prescription(block) }}</p>
              <p class="secondary rec-why">{{ block.recommendation.detail }}</p>
              <p v-if="ramp(block)" class="secondary rec-why">
                <Term id="ramp_up" capitalize />s ({{ ramp(block) }}) are reported but left
                out of the decision - only the sets at the top load drive it.
              </p>
            </div>
          </div>
        </div>
      </section>

      <section v-if="detail.muscle_groups.length" class="card">
        <div class="card-head"><h2 class="card-title">What this session trained</h2></div>
        <p class="card-sub">
          Working sets by primary muscle group. Single-session counts, so read them against
          your weekly targets on the dashboard rather than on their own.
        </p>
        <ul class="muscles">
          <li v-for="group in detail.muscle_groups" :key="group.muscle_group">
            <span class="m-name">{{ titleCase(group.muscle_group) }}</span>
            <span class="m-bar">
              <span :style="{ width: `${(group.sets / maxMuscleSets) * 100}%` }" />
            </span>
            <span class="m-val">{{ group.sets }}</span>
          </li>
        </ul>
      </section>
    </template>
  </div>
</template>

<style scoped>
.page-head {
  margin-bottom: 18px;
}

.back {
  display: inline-block;
  font-size: 12px;
  text-decoration: none;
  margin-bottom: 4px;
}

.back:hover {
  text-decoration: underline;
  text-underline-offset: 3px;
}

.sub {
  margin: 4px 0 0;
  font-size: 13px;
}

.tiles {
  margin-bottom: 16px;
}

.notes {
  margin-bottom: 16px;
}

.notes ul {
  margin: 0;
  padding-left: 18px;
  font-size: 13px;
  color: var(--text-secondary);
}

.notes li + li {
  margin-top: 4px;
}

.plan {
  margin-bottom: 24px;
}

.section-head {
  font-size: 13px;
  color: var(--text-secondary);
  text-transform: uppercase;
  letter-spacing: 0.04em;
  margin-bottom: 10px;
}

.exercise {
  margin-bottom: 12px;
}

.ex-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 12px;
}

.ex-head h3 {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.meta {
  margin: 2px 0 0;
  font-size: 12px;
}

.ex-body {
  display: grid;
  gap: 18px;
}

@media (min-width: 800px) {
  .ex-body {
    grid-template-columns: minmax(0, 5fr) minmax(0, 7fr);
  }
}

.ex-side {
  display: flex;
  flex-direction: column;
  gap: 14px;
}

.compare h4,
.rec h4 {
  margin: 0 0 6px;
  font-size: 11px;
  font-weight: 500;
  text-transform: uppercase;
  letter-spacing: 0.04em;
  color: var(--text-muted);
}

.compare dl {
  margin: 0;
  display: flex;
  gap: 20px;
  flex-wrap: wrap;
  font-size: 13px;
}

.compare dt {
  color: var(--text-secondary);
  font-size: 11px;
}

.compare dd {
  margin: 0;
  font-variant-numeric: tabular-nums;
}

.first-time {
  margin: 0;
  font-size: 12px;
}

.rec {
  border-left: 2px solid var(--series-1);
  padding-left: 12px;
}

.rec-line {
  margin: 0;
  font-size: 16px;
  font-weight: 600;
  letter-spacing: -0.01em;
  font-variant-numeric: tabular-nums;
}

.rec-why {
  margin: 6px 0 0;
  font-size: 12px;
  line-height: 1.5;
}

.pr {
  font-size: 10px;
  font-weight: 500;
  text-transform: uppercase;
  letter-spacing: 0.04em;
  color: var(--success-text);
  border: 1px solid currentcolor;
  border-radius: 5px;
  padding: 1px 5px;
}

.chip {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-size: 12px;
  white-space: nowrap;
}

.dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  display: inline-block;
}

.left {
  text-align: left !important;
}

.target {
  font-weight: 600;
}

.ramp td {
  color: var(--text-muted);
}

.ex-link {
  color: inherit;
  text-decoration: none;
}

.ex-link:hover {
  text-decoration: underline;
  text-underline-offset: 3px;
}

.muscles {
  list-style: none;
  margin: 0;
  padding: 0;
  font-size: 12px;
}

.muscles li {
  display: grid;
  grid-template-columns: 110px minmax(0, 1fr) 32px;
  align-items: center;
  gap: 10px;
  padding: 3px 0;
}

.m-bar {
  background: var(--gridline);
  border-radius: 3px;
  height: 10px;
  overflow: hidden;
}

.m-bar span {
  display: block;
  height: 100%;
  background: var(--series-1);
}

.m-val {
  text-align: right;
  font-variant-numeric: tabular-nums;
  color: var(--text-secondary);
}
</style>
