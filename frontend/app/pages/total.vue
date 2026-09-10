<script setup lang="ts">
/**
 * Your total, its DOTS score, and what the next DOTS marker costs.
 *
 * Its own page because it is only meaningful for a goal judged on a total, and
 * because a lifter who cares about a total cares about it more than about
 * anything else on the strength page. The nav offers it only when the goal
 * tracks one; a hypertrophy log has no main lifts to add up, so arriving here
 * on that goal gets an explanation rather than a zero.
 */
import { computed } from 'vue'
import type { Profile, TotalReport } from '~/types/api'
import { fullDate, titleCase } from '~/utils/format'

const { unit, amount, weight } = useUnits()

const { data: profile } = await useFetch<Profile>('/api/profile', { key: 'profile' })
const { data: total, pending } = await useFetch<TotalReport>('/api/total', {
  query: { days: 365 },
})

const hasTotal = computed(() => Boolean(total.value?.tracks_total && total.value.total_kg > 0))

/** True when the goal totals something other than the three DOTS is scored on -
 *  general strength and its overhead press. */
const totalIsWiderThanDots = computed(
  () => total.value?.dots_total_kg != null && total.value.total_kg > total.value.dots_total_kg,
)

const milestone = computed(() => total.value?.milestone ?? null)
</script>

<template>
  <div>
    <div class="page-head">
      <h1>Your total</h1>
      <p v-if="total && hasTotal" class="secondary">
        {{ titleCase(total.goal) }} goal &middot; {{ titleCase(total.sex) }} &middot;
        {{ weight(total.bodyweight_kg) }}
      </p>
    </div>

    <!-- Reached by URL on a goal with no total, or before anything is logged. -->
    <section v-if="!hasTotal" class="card empty-state">
      <h2>No total for this goal</h2>
      <p class="secondary">
        <template v-if="profile && !profile.tracks_total">
          Your training goal is <strong>{{ titleCase(profile.training_goal) }}</strong>, which
          is judged on weekly volume per muscle group rather than on a total. Choose
          <strong>Strength</strong> or <strong>Powerlifting</strong> in
          <NuxtLink to="/settings">Settings</NuxtLink> and this page fills in.
        </template>
        <template v-else>
          Nothing to add up yet. Import a Hevy CSV export on the
          <NuxtLink to="/">dashboard</NuxtLink> and log the main lifts.
        </template>
      </p>
    </section>

    <template v-else-if="total">
      <section class="card total-card" :class="{ stale: pending }">
        <div class="total-row">
          <div>
            <span class="tile-label secondary"><Term id="total" capitalize /></span>
            <p class="total-value">
              {{ amount(total.total_kg, 0) }}<span class="total-unit secondary">{{ unit }}</span>
            </p>
            <p class="total-of muted">
              {{ total.entries.length }} lifts:
              {{ total.entries.map((entry) => titleCase(entry.lift)).join(' + ') }}
            </p>
          </div>
          <div v-if="total.dots !== null">
            <span class="tile-label secondary"><Term id="dots" capitalize /></span>
            <p class="total-value">{{ total.dots }}</p>
            <p class="total-of muted">
              <template v-if="totalIsWiderThanDots">
                From {{ amount(total.dots_total_kg, 0) }} {{ unit }} of squat, bench and
                deadlift only - the total DOTS is built for.
              </template>
              <template v-else>Bodyweight-adjusted; ~400 is a strong raw lifter.</template>
            </p>
          </div>
        </div>

        <p class="caveat">
          This is a <strong>training</strong> total, not a meet result. Every lift in it is an
          <Term id="e1rm" /> off your working sets, which reads higher than a single on the
          platform on the day - so treat it as "where my training is now".
        </p>

        <p v-if="total.dots_missing.length" class="caveat">
          No DOTS score:
          {{ total.dots_missing.map((lift) => titleCase(lift)).join(' and ') }}
          {{ total.dots_missing.length === 1 ? 'is' : 'are' }} not in the log, and a partial
          total would flatter.
        </p>
        <p v-else-if="total.bodyweight_clamped" class="caveat">
          Your bodyweight sits outside the range the DOTS formula was fitted on, so it was
          clamped to the edge of that range.
        </p>
        <p v-if="total.missing.length" class="caveat">
          Missing from the total:
          {{ total.missing.map((lift) => titleCase(lift)).join(', ') }} - never logged, so
          {{ total.missing.length === 1 ? 'it counts' : 'they count' }} as nothing.
        </p>
      </section>

      <section v-if="milestone" class="card milestone-card">
        <div class="card-head">
          <h2 class="card-title">Breaking down your next milestone</h2>
          <span class="badge">{{ milestone.dots }} DOTS</span>
        </div>
        <p class="card-sub">
          <template v-if="milestone.near_dots !== null">
            You are <strong>{{ amount(milestone.near_add_total_kg) }} {{ unit }}</strong> off
            {{ milestone.near_dots }} DOTS - near enough that it is not worth a plan. The next
            marker worth aiming at is <strong>{{ milestone.dots }}</strong>, which needs
            {{ amount(milestone.total_kg, 0) }} {{ unit }}.
          </template>
          <template v-else>
            {{ milestone.dots }} DOTS needs a total of
            <strong>{{ amount(milestone.total_kg, 0) }} {{ unit }}</strong>.
          </template>
          To add that <strong>{{ amount(milestone.add_total_kg, 0) }} {{ unit }}</strong>, each
          lift owes the share it already contributes - the same percentage from all three:
        </p>

        <ul class="steps">
          <li v-for="lift in milestone.lifts" :key="lift.lift">
            <span class="step-lift">{{ titleCase(lift.lift) }}</span>
            <span class="step-add">+{{ amount(lift.add_kg) }} {{ unit }}</span>
            <span class="step-path muted">
              {{ amount(lift.e1rm_kg) }} &rarr; {{ amount(lift.target_kg) }} {{ unit }}
            </span>
          </li>
        </ul>

        <p class="caveat">
          Those three jumps land you on {{ amount(milestone.reaches_total_kg, 0) }} {{ unit }},
          which scores
          <strong v-if="milestone.reaches_dots !== null">{{ milestone.reaches_dots }}</strong>
          DOTS - targets are snapped to 2.5 {{ unit }} jumps, so the route clears the marker
          rather than landing just short. Splitting it proportionally is arithmetic, not
          coaching: pushing a lagging lift harder is a real strategy, and the ratios below
          are where this app says anything about that.
        </p>
      </section>

      <section class="card table-card">
        <div class="card-head"><h2 class="card-title">Where the total comes from</h2></div>
        <p class="card-sub">Best <Term id="e1rm" /> per lift in the last year.</p>
        <div class="scroll-x">
          <table class="data-table">
            <thead>
              <tr>
                <th>Lift</th>
                <th>Logged as</th>
                <th><Term id="e1rm" capitalize /> ({{ unit }})</th>
                <th>Share</th>
                <th>Sessions</th>
                <th>Last done</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="entry in total.entries" :key="entry.lift">
                <td>{{ titleCase(entry.lift) }}</td>
                <td class="muted">{{ entry.title }}</td>
                <td><strong>{{ amount(entry.e1rm_kg) }}</strong></td>
                <td>{{ entry.share.toFixed(0) }}%</td>
                <td>{{ entry.sessions }}</td>
                <td>{{ fullDate(entry.last_performed) }}</td>
              </tr>
            </tbody>
          </table>
        </div>
      </section>

      <section v-if="total.ratios.length" class="card">
        <div class="card-head"><h2 class="card-title">How the lifts sit together</h2></div>
        <p class="card-sub">
          Against the squat, with wide tolerances - these catch a lift that is genuinely
          lagging, not unusual leverages.
        </p>
        <ul class="ratios">
          <li v-for="ratio in total.ratios" :key="ratio.lift">
            {{ ratio.title }} is <strong>{{ ratio.ratio.toFixed(2) }}x</strong> your squat,
            against {{ ratio.expected.toFixed(2) }}x for a typical raw lifter -
            <span :class="`verdict-${ratio.verdict}`">{{ ratio.verdict }}</span>.
          </li>
        </ul>
      </section>
    </template>
  </div>
</template>

<style scoped>
.page-head {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 16px;
  flex-wrap: wrap;
  margin-bottom: 18px;
}

.page-head p {
  margin: 0;
  font-size: 13px;
}

.total-card,
.milestone-card,
.table-card {
  margin-bottom: 16px;
}

.total-row {
  display: flex;
  flex-wrap: wrap;
  gap: 40px;
}

.tile-label {
  font-size: 12px;
}

.total-value {
  margin: 2px 0 0;
  font-size: 40px;
  font-weight: 600;
  line-height: 1.05;
  letter-spacing: -0.02em;
  font-variant-numeric: tabular-nums;
}

.total-unit {
  font-size: 14px;
  margin-left: 6px;
  letter-spacing: 0;
}

.total-of {
  margin: 6px 0 0;
  font-size: 12px;
  max-width: 42ch;
}

.caveat {
  margin: 14px 0 0;
  font-size: 12px;
  line-height: 1.5;
  color: var(--text-secondary);
  max-width: 76ch;
}

.milestone-card {
  border-left: 3px solid var(--series-1);
}

.badge {
  background: var(--series-1);
  color: #fff;
  font-size: 11px;
  font-weight: 500;
  padding: 2px 9px;
  border-radius: 999px;
  white-space: nowrap;
}

.steps {
  list-style: none;
  margin: 4px 0 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.steps li {
  display: flex;
  align-items: baseline;
  gap: 12px;
  flex-wrap: wrap;
  padding: 9px 12px;
  border: 1px solid var(--border);
  border-radius: 8px;
  background: var(--page);
}

.step-lift {
  font-weight: 500;
  min-width: 9rem;
}

.step-add {
  font-size: 19px;
  font-weight: 600;
  font-variant-numeric: tabular-nums;
  letter-spacing: -0.01em;
  min-width: 6rem;
}

.step-path {
  font-size: 12px;
  font-variant-numeric: tabular-nums;
}

.ratios {
  margin: 0;
  padding-left: 18px;
  font-size: 12px;
  color: var(--text-secondary);
}

.ratios li + li {
  margin-top: 4px;
}

.verdict-lagging {
  color: var(--serious);
}

.verdict-leading {
  color: var(--success-text);
}

.empty-state {
  padding: 36px 24px;
  text-align: center;
}

.empty-state p {
  margin: 10px auto 0;
  max-width: 52ch;
  font-size: 13px;
}
</style>
