<script setup lang="ts">
/** Dashboard: headline stats, volume over time, muscle balance, and findings. */
import { computed, ref } from 'vue'
import type {
  Headline,
  Health,
  Insight,
  MuscleVolume,
  Overview,
  PersonalRecord,
  Profile,
  WeeklyVolume,
} from '~/types/api'
import { compact, fullDate, titleCase } from '~/utils/format'

const { unit, convert, amount, weight } = useUnits()

const range = ref(26)
const RANGES = [
  { value: 12, label: '12w' },
  { value: 26, label: '26w' },
  { value: 52, label: '1y' },
]

const { data: overview, pending: overviewPending } = await useFetch<Overview>('/api/overview')
const { data: weekly, pending: weeklyPending } = await useFetch<WeeklyVolume[]>('/api/volume/weekly', {
  query: computed(() => ({ weeks: range.value })),
})
const { data: muscles } = await useFetch<MuscleVolume[]>('/api/volume/muscle-groups', { query: { days: 28 } })
const { data: insights } = await useFetch<Insight[]>('/api/insights', { query: { days: 180 } })
const { data: records } = await useFetch<PersonalRecord[]>('/api/records', { query: { days: 180, limit: 6 } })

const { data: headline } = await useFetch<Headline>('/api/headline')
const { data: health } = await useFetch<Health>('/api/health')
const { data: profile } = await useFetch<Profile>('/api/profile', { key: 'profile' })
const clearing = ref(false)

/** Ask for the profile once there is a log for it to be wrong about - a form in
 *  front of an empty dashboard is friction before any payoff. */
const askForProfile = computed(() => Boolean(overview.value?.workouts && profile.value?.needs_setup))

async function clearData() {
  if (!window.confirm('Clear all imported workout data? This cannot be undone.')) return
  clearing.value = true
  try {
    await $fetch('/api/data', { method: 'DELETE' })
    await refreshNuxtData()
  } finally {
    clearing.value = false
  }
}

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
    <div class="mb-[18px] flex flex-wrap items-center justify-between gap-4">
      <h1>Dashboard</h1>
      <ImportDropzone
        v-if="overview?.workouts"
        compact
        :hint="health?.imported_file"
        :available-export="health?.available_export"
        @imported="refreshNuxtData()"
      />
      <Button
        variant="destructive"
        size="sm"
        :disabled="clearing"
        title="Clear imported workout data"
        @click="clearData"
      >
        {{ clearing ? 'Clearing...' : 'Clear data' }}
      </Button>
    </div>

    <ImportDropzone
      v-if="!overview?.workouts"
      :available-export="health?.available_export"
      @imported="refreshNuxtData()"
    />

    <template v-else>
      <HeadlineCard :headline="headline" class="mb-4" />

      <ProfileForm v-if="askForProfile" first-run class="border-l-warning mb-5 border-l-[3px]" />

      <div class="mb-5 grid gap-4 md:grid-cols-4" :class="{ stale: overviewPending }">
        <StatTile
          label="Workouts"
          :value="compact(overview?.workouts ?? 0)"
          :spark="spark"
        />
        <StatTile
          :value="compact(convert(overview?.total_volume_kg ?? 0))"
          :unit="unit"
          :delta="volumeDelta"
          delta-label="vs previous 4 weeks"
        >
          <template #label>Total <Term id="volume" /></template>
        </StatTile>
        <StatTile :value="String(overview?.avg_workouts_per_week ?? 0)">
          <template #label><Term id="sessions_per_week" capitalize /></template>
        </StatTile>
        <StatTile :value="compact(overview?.total_sets ?? 0)">
          <template #label><Term id="working_set" capitalize />s</template>
        </StatTile>
      </div>

      <div class="mb-[18px] flex flex-wrap items-center gap-2">
        <Segmented v-model="range" :options="RANGES" label="Time range" />
        <span class="text-muted-foreground">
          {{ fullDate(overview?.first_workout) }} - {{ fullDate(overview?.last_workout) }}
        </span>
      </div>

      <div class="grid gap-4 md:grid-cols-2">
        <ChartCard :empty="bars.length === 0">
          <template #title>Weekly <Term id="volume" /></template>
          <template #subtitle>
            Weight moved per week across <Term id="working_set" />s. Warm-ups excluded.
          </template>
          <div :class="{ stale: weeklyPending }">
            <ColumnChart :bars="bars" :unit="unit" />
          </div>
          <template #table>
            <Table class="numeric-table">
              <TableHeader>
                <TableRow>
                  <TableHead>Week of</TableHead>
                  <TableHead><Term id="volume" capitalize /> ({{ unit }})</TableHead>
                  <TableHead>Sets</TableHead>
                  <TableHead>Sessions</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                <TableRow v-for="week in [...(weekly ?? [])].reverse()" :key="week.week">
                  <TableCell>{{ fullDate(week.week_start) }}</TableCell>
                  <TableCell>{{ amount(week.volume_kg, 0) }}</TableCell>
                  <TableCell>{{ week.sets }}</TableCell>
                  <TableCell>{{ week.workouts }}</TableCell>
                </TableRow>
              </TableBody>
            </Table>
          </template>
        </ChartCard>

        <ChartCard title="Muscle balance" :empty="(muscles ?? []).length === 0">
          <template #subtitle>
            <Term id="sets_per_week" capitalize /> over the last 4 weeks. An exercise's
            secondary muscles count as half a set each.
          </template>
          <MuscleVolumeChart :groups="muscles ?? []" />
          <template #table>
            <Table class="numeric-table">
              <TableHeader>
                <TableRow>
                  <TableHead>Muscle group</TableHead>
                  <TableHead><Term id="sets_per_week" capitalize /></TableHead>
                  <TableHead><Term id="volume" capitalize /> ({{ unit }})</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                <TableRow v-for="group in muscles ?? []" :key="group.muscle_group">
                  <TableCell>{{ titleCase(group.muscle_group) }}</TableCell>
                  <TableCell>{{ group.sets_per_week.toFixed(1) }}</TableCell>
                  <TableCell>{{ amount(group.volume_kg, 0) }}</TableCell>
                </TableRow>
              </TableBody>
            </Table>
          </template>
        </ChartCard>
      </div>

      <div class="mt-4 grid gap-4 md:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle>What to look at</CardTitle>
            <CardDescription>Computed from the log, ordered by severity.</CardDescription>
          </CardHeader>
          <CardContent>
            <p v-if="(insights ?? []).length === 0" class="text-muted-foreground py-7 text-center text-[13px]">
              Nothing flagged in the last 180 days.
            </p>
            <ul v-else class="flex list-none flex-col gap-3.5 p-0">
              <li v-for="(item, i) in (insights ?? []).slice(0, 7)" :key="i" class="flex items-start gap-2.5">
                <span
                  class="mt-[5px] size-2 shrink-0 rounded-full"
                  :style="{ background: severityColor[item.severity] }"
                />
                <div>
                  <strong>{{ item.title }}</strong>
                  <p class="text-muted-foreground mt-0.5 mb-0 text-xs">{{ item.detail }}</p>
                </div>
              </li>
            </ul>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>Recent <Term id="pr" />s</CardTitle>
            <CardDescription>
              Sessions where your <Term id="e1rm" /> beat everything before it.
            </CardDescription>
          </CardHeader>
          <CardContent>
            <p v-if="(records ?? []).length === 0" class="text-muted-foreground py-7 text-center text-[13px]">
              No PRs in the last 180 days.
            </p>
            <Table v-else class="numeric-table">
              <TableHeader>
                <TableRow>
                  <TableHead>Exercise</TableHead>
                  <TableHead>Set</TableHead>
                  <TableHead><Term id="e1rm" capitalize /></TableHead>
                  <TableHead>Date</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                <TableRow v-for="record in records ?? []" :key="`${record.template_id}${record.date}`">
                  <TableCell>{{ record.title }}</TableCell>
                  <TableCell>{{ amount(record.weight_kg) }} x {{ record.reps }}</TableCell>
                  <TableCell>{{ weight(record.e1rm_kg) }}</TableCell>
                  <TableCell>{{ fullDate(record.date) }}</TableCell>
                </TableRow>
              </TableBody>
            </Table>
          </CardContent>
        </Card>
      </div>
    </template>
  </div>
</template>
