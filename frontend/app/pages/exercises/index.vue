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
    <div class="mb-[18px] flex flex-wrap items-center justify-between gap-4">
      <h1>Exercises</h1>
      <Input
        v-model="search"
        type="search"
        class="h-9 w-auto min-w-[220px] text-[13px]"
        placeholder="Filter exercises"
      />
    </div>

    <Card :class="{ stale: pending }">
      <CardContent>
        <p v-if="rows.length === 0" class="text-muted-foreground py-7 text-center text-[13px]">
          {{ search ? 'No exercises match that filter.' : 'No exercises logged yet.' }}
        </p>
        <div v-else class="overflow-x-auto">
          <Table class="numeric-table">
            <TableHeader>
              <TableRow>
                <TableHead>Exercise</TableHead>
                <TableHead>Sessions</TableHead>
                <TableHead>Sets</TableHead>
                <TableHead>Best <Term id="e1rm" /></TableHead>
                <TableHead>{{ unit }}/month</TableHead>
                <TableHead class="text-left!"><Term id="trend" capitalize /></TableHead>
                <TableHead>Last done</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              <TableRow v-for="row in rows" :key="row.template_id">
                <TableCell>
                  <NuxtLink
                    :to="`/exercises/${row.template_id}`"
                    class="text-foreground font-medium no-underline hover:underline hover:underline-offset-[3px]"
                  >
                    {{ row.title }}
                  </NuxtLink>
                </TableCell>
                <TableCell>{{ row.sessions }}</TableCell>
                <TableCell>{{ row.sets }}</TableCell>
                <TableCell>{{ weight(row.best_e1rm_kg) }}</TableCell>
                <TableCell>
                  <template v-if="row.slope !== null">{{ row.slope }}</template>
                  <span v-else class="text-subtle">-</span>
                </TableCell>
                <TableCell class="text-left! whitespace-nowrap">
                  <template v-if="row.style">
                    <span
                      class="mr-1.5 inline-block size-2 rounded-full"
                      :style="{ background: row.style.color }"
                    />
                    {{ row.style.label }}
                  </template>
                  <span v-else class="text-subtle">too few sessions</span>
                </TableCell>
                <TableCell>{{ fullDate(row.last_performed) }}</TableCell>
              </TableRow>
            </TableBody>
          </Table>
        </div>
      </CardContent>
    </Card>
  </div>
</template>
