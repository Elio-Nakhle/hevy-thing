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
    <div class="mb-[18px] flex flex-wrap items-end justify-between gap-4">
      <div>
        <NuxtLink
          to="/exercises"
          class="text-muted-foreground mb-1 inline-block text-xs no-underline hover:underline hover:underline-offset-[3px]"
        >
          &larr; Exercises
        </NuxtLink>
        <h1>{{ summary?.title ?? templateId }}</h1>
      </div>
      <div v-if="summary" class="text-muted-foreground text-[13px]">
        {{ summary.sessions }} sessions - {{ summary.sets }} working sets -
        best {{ weight(summary.best_e1rm_kg) }}
      </div>
    </div>

    <Card v-if="error">
      <CardContent>
        <p class="text-muted-foreground py-7 text-center text-[13px]">
          No sets logged for this exercise.
        </p>
      </CardContent>
    </Card>

    <template v-else>
      <Card v-if="standard" class="mb-4">
        <CardHeader>
          <CardTitle>Against the standards</CardTitle>
        </CardHeader>
        <CardContent>
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
          <p
            v-for="note in standard.score.notes"
            :key="note"
            class="text-muted-foreground mt-2.5 mb-0 text-xs"
          >
            {{ note }}
          </p>
        </CardContent>
      </Card>

      <div class="grid gap-4 md:grid-cols-2">
        <ChartCard
          :empty="e1rmPoints.length === 0"
          empty-message="No scorable sets - an estimate needs both a load and a rep count."
        >
          <template #title><Term id="e1rm" capitalize /></template>
          <template #subtitle>
            Best <Term id="working_set" /> per session, converted with the Epley formula.
          </template>
          <LineChart :points="e1rmPoints" :height="250" :unit="unit" />
          <template #table>
            <Table class="numeric-table">
              <TableHeader>
                <TableRow>
                  <TableHead>Date</TableHead>
                  <TableHead>Top set ({{ unit }})</TableHead>
                  <TableHead><Term id="e1rm" capitalize /></TableHead>
                  <TableHead>Sets</TableHead>
                  <TableHead><Term id="volume" capitalize /> ({{ unit }})</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                <TableRow v-for="point in [...(history ?? [])].reverse()" :key="point.workout_id">
                  <TableCell>{{ fullDate(point.date) }}</TableCell>
                  <TableCell>
                    <template v-if="point.best_weight_kg !== null">
                      {{ amount(point.best_weight_kg) }} x {{ point.top_set_reps }}
                    </template>
                    <span v-else class="text-subtle">-</span>
                  </TableCell>
                  <TableCell>{{ weight(point.best_e1rm_kg) }}</TableCell>
                  <TableCell>{{ point.sets }}</TableCell>
                  <TableCell>{{ amount(point.volume_kg, 0) }}</TableCell>
                </TableRow>
              </TableBody>
            </Table>
          </template>
        </ChartCard>

        <ChartCard :empty="volumeBars.length === 0">
          <template #title><Term id="volume" capitalize /> per session</template>
          <template #subtitle>
            Load times reps across <Term id="working_set" />s.
          </template>
          <ColumnChart :bars="volumeBars" :height="250" :unit="unit" />
          <template #table>
            <Table class="numeric-table">
              <TableHeader>
                <TableRow>
                  <TableHead>Date</TableHead>
                  <TableHead><Term id="volume" capitalize /> ({{ unit }})</TableHead>
                  <TableHead>Sets</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                <TableRow v-for="point in [...(history ?? [])].reverse()" :key="`v${point.workout_id}`">
                  <TableCell>{{ fullDate(point.date) }}</TableCell>
                  <TableCell>{{ amount(point.volume_kg, 0) }}</TableCell>
                  <TableCell>{{ point.sets }}</TableCell>
                </TableRow>
              </TableBody>
            </Table>
          </template>
        </ChartCard>
      </div>
    </template>
  </div>
</template>
