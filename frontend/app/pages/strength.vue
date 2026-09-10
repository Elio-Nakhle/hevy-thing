<script setup lang="ts">
/** Strength standards: every mappable lift against its bodyweight-adjusted bands. */
import { computed } from 'vue'
import type { BenchmarkReport, TotalReport } from '~/types/api'
import { fullDate, titleCase } from '~/utils/format'

const { unit, amount, weight } = useUnits()

const { data: report, pending } = await useFetch<BenchmarkReport>('/api/benchmark', { query: { days: 365 } })
const { data: total } = await useFetch<TotalReport>('/api/total', { query: { days: 365 } })

/** Only shown for a goal that is judged on a total - not hypertrophy, whose
 *  main lifts are empty and whose total is therefore zero. */
const showTotal = computed(() => Boolean(total.value?.tracks_total && total.value.total_kg > 0))

/** True when the goal totals something other than the three DOTS is scored on,
 *  which is the case for general strength and its overhead press. */
const totalIsWiderThanDots = computed(
  () => total.value?.dots_total_kg != null && total.value.total_kg > total.value.dots_total_kg,
)

const entries = computed(() => report.value?.entries ?? [])
const overall = computed(() => report.value?.overall_level_score ?? null)
const caveats = computed(() => report.value?.caveats ?? [])

/** Where the overall score sits on the same 0-4 scale the rows use.
 * A score of `i` is the *threshold* for level `i`, so the five bands span five
 * score units and the divisor is 5, not 4 - dividing by 4 put an elite score at
 * the right edge of the track instead of at the start of the elite band. */
const overallPct = computed(() =>
  overall.value === null ? 0 : Math.max(0, Math.min(100, (overall.value / 5) * 100)),
)
</script>

<template>
  <div>
    <div class="page-head">
      <h1>Strength standards</h1>
      <p v-if="report" class="secondary">
        {{ titleCase(report.sex) }} - {{ weight(report.bodyweight_kg) }}
        <span class="muted">(<Term id="bodyweight_source" />: {{ report.bodyweight_source }})</span>
        <template v-if="report.age"> - age {{ report.age }}</template>
      </p>
    </div>

    <section v-if="caveats.length" class="card caveat-card">
      <p v-for="(caveat, i) in caveats" :key="i" class="caveat">{{ caveat }}</p>
      <p v-if="report?.bodyweight_source === 'default'" class="caveat">
        <NuxtLink to="/settings">Set your bodyweight</NuxtLink> and every band below is
        recomputed.
      </p>
    </section>

    <!-- First for a goal judged on a total: for a powerlifter this *is* the
         headline, and the overall level is the general answer. -->
    <section v-if="showTotal && total" class="card total-card">
      <div class="card-head">
        <h2 class="card-title"><Term id="total" capitalize /></h2>
        <span class="secondary total-goal">{{ titleCase(total.goal) }} goal</span>
      </div>

      <div class="total-row">
        <div>
          <span class="total-value">{{ amount(total.total_kg, 0) }}</span>
          <span class="total-unit secondary">{{ unit }}</span>
          <p class="total-of muted">
            {{ total.entries.length }} lifts:
            {{ total.entries.map((e) => titleCase(e.lift)).join(' + ') }}
          </p>
        </div>
        <div v-if="total.dots !== null">
          <span class="total-value">{{ total.dots }}</span>
          <span class="total-unit secondary"><Term id="dots" /></span>
          <p class="total-of muted">
            <template v-if="totalIsWiderThanDots">
              From {{ amount(total.dots_total_kg, 0) }} {{ unit }} of squat, bench and
              deadlift only - the total DOTS is built for.
            </template>
            <template v-else>Bodyweight-adjusted; ~400 is a strong raw lifter.</template>
          </p>
        </div>
      </div>

      <p class="total-caveat">
        This is a <strong>training</strong> total, not a meet result. Every lift in it is an
        <Term id="e1rm" /> off your working sets, which reads higher than a single on the
        platform on the day - so treat it as "where my training is now".
      </p>

      <p v-if="total.dots_missing.length" class="total-caveat">
        No DOTS score:
        {{ total.dots_missing.map((lift) => titleCase(lift)).join(' and ') }}
        {{ total.dots_missing.length === 1 ? 'is' : 'are' }} not in the log, and a partial
        total would flatter.
      </p>
      <p v-else-if="total.bodyweight_clamped" class="total-caveat">
        Your bodyweight sits outside the range the DOTS formula was fitted on, so it was
        clamped to the edge of that range.
      </p>

      <p v-if="total.missing.length" class="total-caveat">
        Missing from the total:
        {{ total.missing.map((lift) => titleCase(lift)).join(', ') }} - never logged, so
        {{ total.missing.length === 1 ? 'it counts' : 'they count' }} as nothing.
      </p>

      <table class="data-table total-table">
        <thead>
          <tr>
            <th>Lift</th>
            <th>Logged as</th>
            <th><Term id="e1rm" capitalize /> ({{ unit }})</th>
            <th>Share</th>
            <th>Last done</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="entry in total.entries" :key="entry.lift">
            <td>{{ titleCase(entry.lift) }}</td>
            <td class="muted">{{ entry.title }}</td>
            <td><strong>{{ amount(entry.e1rm_kg) }}</strong></td>
            <td>{{ entry.share.toFixed(0) }}%</td>
            <td>{{ fullDate(entry.last_performed) }}</td>
          </tr>
        </tbody>
      </table>

      <ul v-if="total.ratios.length" class="ratios">
        <li v-for="ratio in total.ratios" :key="ratio.lift">
          {{ ratio.title }} is <strong>{{ ratio.ratio.toFixed(2) }}x</strong> your squat,
          against {{ ratio.expected.toFixed(2) }}x for a typical raw lifter -
          <span :class="`verdict-${ratio.verdict}`">{{ ratio.verdict }}</span>.
        </li>
      </ul>
    </section>

    <section v-if="overall !== null" class="card hero-card">
      <span class="tile-label secondary">Overall <Term id="level" /></span>
      <div class="hero-row">
        <span class="hero">{{ report?.overall_level }}</span>
        <span class="hero-score secondary">{{ overall.toFixed(2) }} / 4</span>
      </div>
      <div class="hero-track" role="img"
           :aria-label="`Overall level score ${overall.toFixed(2)} out of 4`">
        <span
          v-for="i in 5"
          :key="i"
          class="hero-band"
          :style="{ background: `var(--level-${i})` }"
        />
        <span class="hero-marker" :style="{ left: `${overallPct}%` }" />
      </div>
      <p class="secondary hero-note">
        The mean <Term id="level_score" /> of every lift below: 0 beginner, 2 intermediate,
        4 elite. This is where you stand against other lifters - for whether you are
        getting stronger, the <NuxtLink to="/">dashboard</NuxtLink> answers against your own
        past self.
      </p>
    </section>

    <section class="card rows-card" :class="{ stale: pending }">
      <div class="card-head"><h2 class="card-title">By lift</h2></div>
      <p class="card-sub">
        Best <Term id="e1rm" /> in the last year, placed on the bands for your bodyweight.
        Hover a band to see its threshold.
      </p>

      <p v-if="entries.length === 0" class="empty">
        Nothing to benchmark yet. Import a Hevy CSV export first.
      </p>

      <div v-else>
        <StandardsRow
          v-for="(entry, i) in entries"
          :key="entry.template_id"
          :title="entry.title"
          :e1rm="entry.score.e1rm_kg"
          :level-score="entry.score.level_score"
          :level="entry.score.level"
          :thresholds="entry.score.thresholds"
          :next-level="entry.score.next_level"
          :kg-to-next="entry.score.kg_to_next_level"
          :show-scale="i === entries.length - 1"
        >
          <p v-if="entry.also_logged?.length" class="also secondary">
            Also logged against this standard, and weaker:
            {{ entry.also_logged.join(', ') }}
          </p>
        </StandardsRow>
      </div>
    </section>

    <section v-if="entries.length" class="card table-card">
      <div class="card-head"><h2 class="card-title">Thresholds</h2></div>
      <p class="card-sub">
        The same numbers as a table - kilograms required at each level for your bodyweight.
      </p>
      <div class="scroll-x">
        <table class="data-table">
          <thead>
            <tr>
              <th>Exercise</th>
              <th><Term id="e1rm" capitalize /> ({{ unit }})</th>
              <th>Beginner</th>
              <th>Novice</th>
              <th>Intermediate</th>
              <th>Advanced</th>
              <th>Elite</th>
              <th>Last done</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="entry in entries" :key="entry.template_id">
              <td>{{ entry.title }}</td>
              <td><strong>{{ amount(entry.score.e1rm_kg) }}</strong></td>
              <td>{{ amount(entry.score.thresholds.beginner) }}</td>
              <td>{{ amount(entry.score.thresholds.novice) }}</td>
              <td>{{ amount(entry.score.thresholds.intermediate) }}</td>
              <td>{{ amount(entry.score.thresholds.advanced) }}</td>
              <td>{{ amount(entry.score.thresholds.elite) }}</td>
              <td>{{ fullDate(entry.last_performed) }}</td>
            </tr>
          </tbody>
        </table>
      </div>
      <p class="source secondary">
        Standards from
        <a href="https://strengthlevel.com/strength-standards" target="_blank" rel="noopener">
          strengthlevel.com
        </a>, interpolated to your exact bodyweight. The band names are
        <Term id="percentile" />s of lifts logged on that site - beginner is the 5th, novice
        the 20th, intermediate the 50th, advanced the 80th, elite the 95th - so they rank you
        against people who track their training, not against the general population.
      </p>
    </section>

    <section v-if="(report?.unmapped ?? []).length" class="card table-card">
      <div class="card-head"><h2 class="card-title">Not benchmarked</h2></div>
      <p class="card-sub">
        No published load standard matches these. Bodyweight and timed movements -
        sit-ups, planks, hanging leg raises - have rep and time standards only, so there
        is nothing to score a load against. If one of these <em>is</em> a load exercise,
        add a rule to <code>backend/src/hevy_coach/data/exercise_map.json</code>.
      </p>
      <ul class="unmapped">
        <li v-for="item in report?.unmapped ?? []" :key="item.template_id">
          {{ item.title }} <span class="muted">({{ item.sessions }} sessions)</span>
        </li>
      </ul>
    </section>
  </div>
</template>

<style scoped>
.caveat-card {
  border-left: 3px solid var(--warning);
}

.caveat {
  margin: 0;
  font-size: 13px;
  line-height: 1.5;
}

.caveat + .caveat {
  margin-top: 8px;
}

.also {
  margin: 2px 0 0;
  font-size: 12px;
}

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

.total-card {
  margin-bottom: 16px;
  border-left: 3px solid var(--series-1);
}

.total-goal {
  font-size: 12px;
  text-transform: capitalize;
}

.total-row {
  display: flex;
  flex-wrap: wrap;
  gap: 32px;
  margin: 6px 0 4px;
}

.total-value {
  font-size: 38px;
  font-weight: 600;
  line-height: 1.05;
  letter-spacing: -0.02em;
  font-variant-numeric: tabular-nums;
}

.total-unit {
  font-size: 14px;
  margin-left: 6px;
}

.total-of {
  margin: 4px 0 0;
  font-size: 12px;
  max-width: 40ch;
}

.total-caveat {
  margin: 12px 0 0;
  font-size: 12px;
  line-height: 1.5;
  color: var(--text-secondary);
  max-width: 74ch;
}

.total-table {
  margin-top: 14px;
}

.ratios {
  margin: 12px 0 0;
  padding-left: 18px;
  font-size: 12px;
  color: var(--text-secondary);
}

.ratios li + li {
  margin-top: 3px;
}

.verdict-lagging {
  color: var(--serious);
}

.verdict-leading {
  color: var(--success-text);
}

.hero-card {
  margin-bottom: 16px;
}

.hero-row {
  display: flex;
  align-items: baseline;
  gap: 12px;
  margin: 2px 0 12px;
}

.hero {
  font-size: 40px;
  font-weight: 600;
  line-height: 1.05;
  letter-spacing: -0.02em;
  text-transform: capitalize;
}

.hero-score {
  font-size: 14px;
}

.hero-track {
  position: relative;
  display: flex;
  gap: 2px;
  height: 14px;
}

.hero-band {
  flex: 1;
  border-radius: 2px;
}

.hero-marker {
  position: absolute;
  top: -4px;
  bottom: -4px;
  width: 2px;
  background: var(--text-primary);
  border-radius: 2px;
  box-shadow: 0 0 0 2px var(--surface-1);
  transform: translateX(-1px);
}

.hero-note {
  margin: 12px 0 0;
  font-size: 12px;
}

.rows-card,
.table-card {
  margin-bottom: 16px;
}

.source {
  margin: 12px 0 0;
  font-size: 12px;
}

.unmapped {
  margin: 0;
  padding-left: 18px;
  columns: 2;
  font-size: 12px;
  color: var(--text-secondary);
}

code {
  font-size: 11px;
  background: var(--page);
  padding: 2px 5px;
  border-radius: 4px;
}
</style>
