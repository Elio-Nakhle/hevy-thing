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
    <div class="page-head">
      <div>
        <h1>Workouts</h1>
        <p class="secondary sub">
          Open a session for what it did to each lift and what to load next time.
        </p>
      </div>
    </div>

    <div v-if="routines.length > 1" class="filters">
      <div class="seg" role="group" aria-label="Routine">
        <button type="button" :aria-pressed="routine === 'all'" @click="routine = 'all'">
          All
        </button>
        <button
          v-for="option in routines"
          :key="option.title"
          type="button"
          :aria-pressed="routine === option.title"
          @click="routine = option.title"
        >
          {{ option.title }} ({{ option.runs }})
        </button>
      </div>
    </div>

    <section class="card" :class="{ stale: pending }">
      <p v-if="rows.length === 0" class="empty">No sessions logged yet.</p>
      <div v-else class="scroll-x">
        <table class="data-table">
          <thead>
            <tr>
              <th>Date</th>
              <th>Routine</th>
              <th>Run</th>
              <th>Exercises</th>
              <th>Sets</th>
              <th>Volume ({{ unit }})</th>
              <th>vs previous run</th>
              <th>Duration</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="row in rows" :key="row.id">
              <td>
                <NuxtLink :to="`/workouts/${row.id}`" class="row-link">
                  {{ fullDate(row.start_time) }}
                </NuxtLink>
              </td>
              <td class="left">{{ row.title }}</td>
              <td class="muted">{{ row.routine_index }} / {{ row.routine_runs }}</td>
              <td>{{ row.exercises }}</td>
              <td>{{ row.sets }}</td>
              <td>{{ amount(row.volume_kg, 0) }}</td>
              <td>
                <span
                  v-if="deltas.get(row.id) !== undefined"
                  :style="{ color: (deltas.get(row.id) as number) >= 0 ? 'var(--success-text)' : 'var(--text-secondary)' }"
                >
                  {{ (deltas.get(row.id) as number) >= 0 ? '+' : '' }}{{ (deltas.get(row.id) as number).toFixed(0) }}%
                </span>
                <span v-else class="muted">-</span>
              </td>
              <td>
                <template v-if="row.duration_minutes">{{ Math.round(row.duration_minutes) }} min</template>
                <span v-else class="muted">-</span>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </section>
  </div>
</template>

<style scoped>
.page-head {
  margin-bottom: 18px;
}

.sub {
  margin: 4px 0 0;
  font-size: 13px;
}

.left {
  text-align: left !important;
}

.row-link {
  color: var(--text-primary);
  text-decoration: none;
  font-weight: 500;
}

.row-link:hover {
  text-decoration: underline;
  text-underline-offset: 3px;
}
</style>
