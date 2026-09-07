<script setup lang="ts">
/** One exercise: e1RM progression, per-session volume, and standing vs standards. */
import { computed } from 'vue'
import { useRoute } from 'vue-router'
import type { BenchmarkReport, ExerciseSummary, SessionPoint } from '~/types/api'
import { fullDate } from '~/utils/format'

const { unit, convert, amount, weight } = useUnits()

const route = useRoute()
const templateId = computed(() => String(route.params.id))

const { data: history, error } = await useFetch<SessionPoint[]>(
  () => `/api/exercises/${templateId.value}/history`,
  { query: { days: 730 } },
)
const { data: summaries } = await useFetch<ExerciseSummary[]>('/api/exercises', { query: { days: 730 } })
const { data: benchmark } = await useFetch<BenchmarkReport>('/api/benchmark', { query: { days: 730 } })

const summary = computed(() =>
  (summaries.value ?? []).find((s) => s.template_id === templateId.value),
)

const standard = computed(() =>
  (benchmark.value?.entries ?? []).find((e) => e.template_id === templateId.value),
)

const e1rmPoints = computed(() =>
  (history.value ?? [])
    .filter((p) => p.best_e1rm_kg !== null)
    .map((p) => ({ date: p.date, value: convert(p.best_e1rm_kg as number) })),
)

const volumeBars = computed(() =>
  (history.value ?? []).map((p) => ({ label: p.date, value: convert(p.volume_kg) })),
)
</script>

<template>
  <div>
    <div class="page-head">
      <div>
        <NuxtLink to="/exercises" class="back secondary">&larr; Exercises</NuxtLink>
        <h1>{{ summary?.title ?? templateId }}</h1>
      </div>
      <div v-if="summary" class="head-stats secondary">
        {{ summary.sessions }} sessions - {{ summary.sets }} working sets -
        best {{ weight(summary.best_e1rm_kg) }}
      </div>
    </div>

    <p v-if="error" class="card empty">
      No sets logged for this exercise.
    </p>

    <template v-else>
      <section v-if="standard" class="card standard-card">
        <div class="card-head"><h2 class="card-title">Against the standards</h2></div>
        <StandardsRow
          :title="standard.title"
          :e1rm="standard.score.e1rm_kg"
          :level-score="standard.score.level_score"
          :level="standard.score.level"
          :thresholds="standard.score.thresholds"
          :next-level="standard.score.next_level"
          :kg-to-next="standard.score.kg_to_next_level"
          show-scale
        />
        <p v-for="note in standard.score.notes" :key="note" class="note secondary">{{ note }}</p>
      </section>

      <div class="grid grid-2">
        <ChartCard
          title="Estimated 1RM"
          subtitle="Best working set per session, converted with the Epley formula."
          :empty="e1rmPoints.length === 0"
          empty-message="No scorable sets - e1RM needs both a load and a rep count."
        >
          <LineChart :points="e1rmPoints" :height="250" :unit="unit" />
          <template #table>
            <table class="data-table">
              <thead>
                <tr><th>Date</th><th>Top set ({{ unit }})</th><th>e1RM</th><th>Sets</th><th>Volume ({{ unit }})</th></tr>
              </thead>
              <tbody>
                <tr v-for="point in [...(history ?? [])].reverse()" :key="point.workout_id">
                  <td>{{ fullDate(point.date) }}</td>
                  <td>
                    <template v-if="point.best_weight_kg !== null">
                      {{ amount(point.best_weight_kg) }} x {{ point.top_set_reps }}
                    </template>
                    <span v-else class="muted">-</span>
                  </td>
                  <td>{{ weight(point.best_e1rm_kg) }}</td>
                  <td>{{ point.sets }}</td>
                  <td>{{ amount(point.volume_kg, 0) }}</td>
                </tr>
              </tbody>
            </table>
          </template>
        </ChartCard>

        <ChartCard
          title="Volume per session"
          subtitle="Load times reps across working sets."
          :empty="volumeBars.length === 0"
        >
          <ColumnChart :bars="volumeBars" :height="250" :unit="unit" />
          <template #table>
            <table class="data-table">
              <thead><tr><th>Date</th><th>Volume ({{ unit }})</th><th>Sets</th></tr></thead>
              <tbody>
                <tr v-for="point in [...(history ?? [])].reverse()" :key="`v${point.workout_id}`">
                  <td>{{ fullDate(point.date) }}</td>
                  <td>{{ amount(point.volume_kg, 0) }}</td>
                  <td>{{ point.sets }}</td>
                </tr>
              </tbody>
            </table>
          </template>
        </ChartCard>
      </div>
    </template>
  </div>
</template>

<style scoped>
.page-head {
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  gap: 16px;
  flex-wrap: wrap;
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

.head-stats {
  font-size: 13px;
}

.standard-card {
  margin-bottom: 16px;
}

.note {
  margin: 10px 0 0;
  font-size: 12px;
}
</style>
