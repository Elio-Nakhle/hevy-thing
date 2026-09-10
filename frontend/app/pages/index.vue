<script setup lang="ts">
/** Dashboard: headline stats, volume over time, muscle balance, and findings. */
import { computed, ref } from 'vue'
import type {
  Health,
  Insight,
  MuscleVolume,
  Overview,
  PersonalRecord,
  WeeklyVolume,
} from '~/types/api'
import { compact, fullDate, titleCase } from '~/utils/format'

const { unit, convert, amount, weight } = useUnits()

const range = ref(26)
const RANGES = [
  { weeks: 12, label: '12w' },
  { weeks: 26, label: '26w' },
  { weeks: 52, label: '1y' },
]

const { data: overview, pending: overviewPending } = await useFetch<Overview>('/api/overview')
const { data: weekly, pending: weeklyPending } = await useFetch<WeeklyVolume[]>('/api/volume/weekly', {
  query: computed(() => ({ weeks: range.value })),
})
const { data: muscles } = await useFetch<MuscleVolume[]>('/api/volume/muscle-groups', { query: { days: 28 } })
const { data: insights } = await useFetch<Insight[]>('/api/insights', { query: { days: 180 } })
const { data: records } = await useFetch<PersonalRecord[]>('/api/records', { query: { days: 180, limit: 6 } })

const { data: health } = await useFetch<Health>('/api/health')

const bars = computed(() =>
  (weekly.value ?? []).map((week) => ({ label: week.week_start, value: convert(week.volume_kg) })),
)

/** Volume change of the last 4 weeks against the 4 before them. */
const volumeDelta = computed(() => {
  const series = weekly.value ?? []
  if (series.length < 8) return null
  const mean = (rows: typeof series) => rows.reduce((a, b) => a + b.volume_kg, 0) / rows.length
  const recent = mean(series.slice(-4))
  const earlier = mean(series.slice(-8, -4))
  return earlier > 0 ? ((recent - earlier) / earlier) * 100 : null
})

const spark = computed(() => (weekly.value ?? []).slice(-12).map((w) => convert(w.volume_kg)))

const severityColor: Record<string, string> = {
  warning: 'var(--critical)',
  suggestion: 'var(--warning)',
  info: 'var(--series-1)',
}
</script>

<template>
  <div>
    <div class="page-head">
      <h1>Dashboard</h1>
      <ImportDropzone
        v-if="overview?.workouts"
        compact
        :hint="health?.imported_file"
        :available-export="health?.available_export"
        @imported="refreshNuxtData()"
      />
    </div>

    <ImportDropzone
      v-if="!overview?.workouts"
      :available-export="health?.available_export"
      @imported="refreshNuxtData()"
    />

    <template v-else>
      <div class="grid grid-4 tiles" :class="{ stale: overviewPending }">
        <StatTile
          label="Workouts"
          :value="compact(overview?.workouts ?? 0)"
          :spark="spark"
        />
        <StatTile
          label="Total volume"
          :value="compact(convert(overview?.total_volume_kg ?? 0))"
          :unit="unit"
          :delta="volumeDelta"
          delta-label="vs previous 4 weeks"
        />
        <StatTile
          label="Sessions per week"
          :value="String(overview?.avg_workouts_per_week ?? 0)"
        />
        <StatTile
          label="Working sets"
          :value="compact(overview?.total_sets ?? 0)"
        />
      </div>

      <div class="filters">
        <div class="seg" role="group" aria-label="Time range">
          <button
            v-for="option in RANGES"
            :key="option.weeks"
            type="button"
            :aria-pressed="range === option.weeks"
            @click="range = option.weeks"
          >
            {{ option.label }}
          </button>
        </div>
        <span class="secondary">
          {{ fullDate(overview?.first_workout) }} - {{ fullDate(overview?.last_workout) }}
        </span>
      </div>

      <div class="grid grid-2">
        <ChartCard
          title="Weekly training volume"
          subtitle="Tonnage per week from working sets. Warm-ups excluded."
          :empty="bars.length === 0"
        >
          <div :class="{ stale: weeklyPending }">
            <ColumnChart :bars="bars" :unit="unit" />
          </div>
          <template #table>
            <table class="data-table">
              <thead>
                <tr><th>Week of</th><th>Volume ({{ unit }})</th><th>Sets</th><th>Sessions</th></tr>
              </thead>
              <tbody>
                <tr v-for="week in [...(weekly ?? [])].reverse()" :key="week.week">
                  <td>{{ fullDate(week.week_start) }}</td>
                  <td>{{ amount(week.volume_kg, 0) }}</td>
                  <td>{{ week.sets }}</td>
                  <td>{{ week.workouts }}</td>
                </tr>
              </tbody>
            </table>
          </template>
        </ChartCard>

        <ChartCard
          title="Muscle balance"
          subtitle="Working sets per week over the last 4 weeks. Secondary muscles count as half a set."
          :empty="(muscles ?? []).length === 0"
        >
          <MuscleVolumeChart :groups="muscles ?? []" />
          <template #table>
            <table class="data-table">
              <thead>
                <tr><th>Muscle group</th><th>Sets/week</th><th>Volume ({{ unit }})</th></tr>
              </thead>
              <tbody>
                <tr v-for="group in muscles ?? []" :key="group.muscle_group">
                  <td>{{ titleCase(group.muscle_group) }}</td>
                  <td>{{ group.sets_per_week.toFixed(1) }}</td>
                  <td>{{ amount(group.volume_kg, 0) }}</td>
                </tr>
              </tbody>
            </table>
          </template>
        </ChartCard>
      </div>

      <div class="grid grid-2 second-row">
        <section class="card">
          <div class="card-head"><h2 class="card-title">What to look at</h2></div>
          <p class="card-sub">Computed from the log, ordered by severity.</p>
          <p v-if="(insights ?? []).length === 0" class="empty">
            Nothing flagged in the last 180 days.
          </p>
          <ul v-else class="insight-list">
            <li v-for="(item, i) in (insights ?? []).slice(0, 7)" :key="i">
              <span class="dot" :style="{ background: severityColor[item.severity] }" />
              <div>
                <strong>{{ item.title }}</strong>
                <p class="secondary">{{ item.detail }}</p>
              </div>
            </li>
          </ul>
        </section>

        <section class="card">
          <div class="card-head"><h2 class="card-title">Recent personal records</h2></div>
          <p class="card-sub">Sessions where estimated 1RM beat everything before it.</p>
          <p v-if="(records ?? []).length === 0" class="empty">No PRs in the last 180 days.</p>
          <table v-else class="data-table">
            <thead>
              <tr><th>Exercise</th><th>Set</th><th>e1RM</th><th>Date</th></tr>
            </thead>
            <tbody>
              <tr v-for="record in records ?? []" :key="`${record.template_id}${record.date}`">
                <td>{{ record.title }}</td>
                <td>{{ amount(record.weight_kg) }} x {{ record.reps }}</td>
                <td>{{ weight(record.e1rm_kg) }}</td>
                <td>{{ fullDate(record.date) }}</td>
              </tr>
            </tbody>
          </table>
        </section>
      </div>
    </template>
  </div>
</template>

<style scoped>
.page-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  margin-bottom: 18px;
  flex-wrap: wrap;
}

.tiles {
  margin-bottom: 20px;
}

.second-row {
  margin-top: 16px;
}

.insight-list {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 14px;
}

.insight-list li {
  display: flex;
  gap: 10px;
  align-items: flex-start;
}

.insight-list p {
  margin: 2px 0 0;
  font-size: 12px;
}

.dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  margin-top: 5px;
  flex: none;
}
</style>
