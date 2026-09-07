<script setup lang="ts">
/** Every trained exercise, with its trend classification. */
import { computed, ref } from 'vue'
import type { ExerciseSummary, ExerciseTrend } from '~/types/api'
import { fullDate } from '~/utils/format'

const { unit, amount, weight } = useUnits()

const TREND_STYLE: Record<string, { label: string; color: string }> = {
  progressing: { label: 'Progressing', color: 'var(--success-text)' },
  maintaining: { label: 'Maintaining', color: 'var(--text-secondary)' },
  stalling: { label: 'Stalling', color: 'var(--warning)' },
  regressing: { label: 'Regressing', color: 'var(--critical)' },
}

const search = ref('')
const { data: summaries, pending } = await useFetch<ExerciseSummary[]>('/api/exercises', {
  query: { days: 365 },
})
const { data: trends } = await useFetch<ExerciseTrend[]>('/api/trends', { query: { days: 365 } })

const trendById = computed(
  () => new Map((trends.value ?? []).map((trend) => [trend.template_id, trend])),
)

/** Rows with their trend resolved here, so the template never re-indexes a lookup. */
const rows = computed(() => {
  const term = search.value.trim().toLowerCase()
  return (summaries.value ?? [])
    .filter((summary) => !term || summary.title.toLowerCase().includes(term))
    .map((summary) => {
      // Not every exercise has enough sessions for a trend fit.
      const trend = trendById.value.get(summary.template_id)
      return {
        ...summary,
        slope: trend
          ? `${trend.slope_kg_per_month > 0 ? '+' : ''}${amount(trend.slope_kg_per_month)}`
          : null,
        style: (trend && TREND_STYLE[trend.trend]) || null,
      }
    })
})
</script>

<template>
  <div>
    <div class="page-head">
      <h1>Exercises</h1>
      <input v-model="search" class="search" type="search" placeholder="Filter exercises" />
    </div>

    <section class="card" :class="{ stale: pending }">
      <p v-if="rows.length === 0" class="empty">
        {{ search ? 'No exercises match that filter.' : 'No exercises logged yet.' }}
      </p>
      <div v-else class="scroll-x">
        <table class="data-table">
          <thead>
            <tr>
              <th>Exercise</th>
              <th>Sessions</th>
              <th>Sets</th>
              <th>Best e1RM</th>
              <th>{{ unit }}/month</th>
              <th>Trend</th>
              <th>Last done</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="row in rows" :key="row.template_id">
              <td>
                <NuxtLink :to="`/exercises/${row.template_id}`" class="ex-link">
                  {{ row.title }}
                </NuxtLink>
              </td>
              <td>{{ row.sessions }}</td>
              <td>{{ row.sets }}</td>
              <td>{{ weight(row.best_e1rm_kg) }}</td>
              <td>
                <template v-if="row.slope !== null">{{ row.slope }}</template>
                <span v-else class="muted">-</span>
              </td>
              <td class="trend-cell">
                <template v-if="row.style">
                  <span class="dot" :style="{ background: row.style.color }" />
                  {{ row.style.label }}
                </template>
                <span v-else class="muted">too few sessions</span>
              </td>
              <td>{{ fullDate(row.last_performed) }}</td>
            </tr>
          </tbody>
        </table>
      </div>
    </section>
  </div>
</template>

<style scoped>
.page-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  flex-wrap: wrap;
  margin-bottom: 18px;
}

.search {
  border: 1px solid var(--border);
  background: var(--surface-1);
  color: var(--text-primary);
  border-radius: 8px;
  padding: 7px 11px;
  font: inherit;
  font-size: 13px;
  min-width: 220px;
}

.ex-link {
  color: var(--text-primary);
  text-decoration: none;
  font-weight: 500;
}

.ex-link:hover {
  text-decoration: underline;
  text-underline-offset: 3px;
}

.trend-cell {
  text-align: left !important;
  white-space: nowrap;
}

.dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  display: inline-block;
  margin-right: 6px;
}
</style>
