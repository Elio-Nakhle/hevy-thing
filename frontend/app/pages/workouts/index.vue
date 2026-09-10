<script setup lang="ts">
/** Every logged session, grouped by the routine it belongs to. */
import { computed, ref } from 'vue'
import type { WorkoutSummary } from '~/types/api'
import { fullDate } from '~/utils/format'

const { unit, amount } = useUnits()

const { data: workouts, pending } = await useFetch<WorkoutSummary[]>('/api/workouts', {
  query: { limit: 200 },
})

const routine = ref('all')

/** Routine names by how often they have been run - the repeat ones first. */
const routines = computed(() => {
  const counts = new Map<string, number>()
  for (const workout of workouts.value ?? []) {
    counts.set(workout.title, (counts.get(workout.title) ?? 0) + 1)
  }
  return [...counts.entries()]
    .sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]))
    .map(([title, runs]) => ({ title, runs }))
})

const routineOptions = computed(() => [
  { value: 'all', label: 'All' },
  ...routines.value.map((option) => ({
    value: option.title,
    label: `${option.title} (${option.runs})`,
  })),
])

const rows = computed(() =>
  (workouts.value ?? []).filter((w) => routine.value === 'all' || w.title === routine.value),
)

/** Tonnage against the previous run of the same routine, for an at-a-glance trend. */
const deltas = computed(() => {
  const byRoutine = new Map<string, WorkoutSummary[]>()
  for (const workout of workouts.value ?? []) {
    const list = byRoutine.get(workout.title) ?? []
    list.push(workout)
    byRoutine.set(workout.title, list)
  }
  const result = new Map<string, number>()
  for (const list of byRoutine.values()) {
    // The API returns newest first, so the next entry is the previous run.
    list.forEach((workout, index) => {
      const previous = list[index + 1]
      if (previous && previous.volume_kg > 0) {
        result.set(workout.id, ((workout.volume_kg - previous.volume_kg) / previous.volume_kg) * 100)
      }
    })
  }
  return result
})
</script>

<template>
  <div>
    <div class="mb-[18px]">
      <h1>Workouts</h1>
      <p class="text-muted-foreground mt-1 mb-0 text-[13px]">
        Open a session for what it did to each lift and what to load next time.
      </p>
    </div>

    <div v-if="routines.length > 1" class="mb-[18px] max-w-full overflow-x-auto">
      <Segmented v-model="routine" :options="routineOptions" label="Routine" />
    </div>

    <Card :class="{ stale: pending }">
      <CardContent>
        <p v-if="rows.length === 0" class="text-muted-foreground py-7 text-center text-[13px]">
          No sessions logged yet.
        </p>
        <div v-else class="overflow-x-auto">
          <Table class="numeric-table">
            <TableHeader>
              <TableRow>
                <TableHead>Date</TableHead>
                <TableHead class="text-left!">Routine</TableHead>
                <TableHead>Run</TableHead>
                <TableHead>Exercises</TableHead>
                <TableHead>Sets</TableHead>
                <TableHead>Volume ({{ unit }})</TableHead>
                <TableHead>vs previous run</TableHead>
                <TableHead>Duration</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              <TableRow v-for="row in rows" :key="row.id">
                <TableCell>
                  <NuxtLink
                    :to="`/workouts/${row.id}`"
                    class="text-foreground font-medium no-underline hover:underline hover:underline-offset-[3px]"
                  >
                    {{ fullDate(row.start_time) }}
                  </NuxtLink>
                </TableCell>
                <TableCell class="text-left!">{{ row.title }}</TableCell>
                <TableCell class="text-subtle">{{ row.routine_index }} / {{ row.routine_runs }}</TableCell>
                <TableCell>{{ row.exercises }}</TableCell>
                <TableCell>{{ row.sets }}</TableCell>
                <TableCell>{{ amount(row.volume_kg, 0) }}</TableCell>
                <TableCell>
                  <span
                    v-if="deltas.get(row.id) !== undefined"
                    :style="{ color: (deltas.get(row.id) as number) >= 0 ? 'var(--success-text)' : 'var(--text-secondary)' }"
                  >
                    {{ (deltas.get(row.id) as number) >= 0 ? '+' : '' }}{{ (deltas.get(row.id) as number).toFixed(0) }}%
                  </span>
                  <span v-else class="text-subtle">-</span>
                </TableCell>
                <TableCell>
                  <template v-if="row.duration_minutes">{{ Math.round(row.duration_minutes) }} min</template>
                  <span v-else class="text-subtle">-</span>
                </TableCell>
              </TableRow>
            </TableBody>
          </Table>
        </div>
      </CardContent>
    </Card>
  </div>
</template>
