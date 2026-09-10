<script setup lang="ts">
/** Strength standards: every mappable lift against its bodyweight-adjusted bands. */
import { computed } from 'vue'
import type { BenchmarkReport, Profile } from '~/types/api'
import { fullDate, titleCase } from '~/utils/format'

const { unit, amount, weight } = useUnits()

const { data: report, pending } = await useFetch<BenchmarkReport>('/api/benchmark', { query: { days: 365 } })
const { data: profile } = await useFetch<Profile>('/api/profile', { key: 'profile' })

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
    <div class="mb-[18px] flex flex-wrap items-baseline justify-between gap-4">
      <h1>Strength standards</h1>
      <p v-if="report" class="text-muted-foreground m-0 text-[13px]">
        {{ titleCase(report.sex) }} - {{ weight(report.bodyweight_kg) }}
        <span class="text-subtle">(<Term id="bodyweight_source" />: {{ report.bodyweight_source }})</span>
        <template v-if="report.age"> - age {{ report.age }}</template>
      </p>
    </div>

    <Card v-if="caveats.length" class="border-l-warning border-l-[3px]">
      <CardContent>
        <p v-for="(caveat, i) in caveats" :key="i" class="m-0 text-[13px] leading-normal [&+p]:mt-2">
          {{ caveat }}
        </p>
        <p
          v-if="report?.bodyweight_source === 'default'"
          class="m-0 text-[13px] leading-normal [&+p]:mt-2"
        >
          <NuxtLink to="/settings">Set your bodyweight</NuxtLink> and every band below is
          recomputed.
        </p>
      </CardContent>
    </Card>

    <p v-if="profile?.tracks_total" class="text-muted-foreground mt-4 mb-4 text-[13px]">
      Your training total and its DOTS score are on the
      <NuxtLink to="/total">Total</NuxtLink> page.
    </p>

    <Card v-if="overall !== null" class="mb-4">
      <CardContent>
        <span class="text-muted-foreground text-xs">Overall <Term id="level" /></span>
        <div class="mt-0.5 mb-3 flex items-baseline gap-3">
          <span class="text-[40px] leading-[1.05] font-semibold tracking-[-0.02em] capitalize">
            {{ report?.overall_level }}
          </span>
          <span class="text-muted-foreground text-sm">{{ overall.toFixed(2) }} / 4</span>
        </div>
        <div
          class="relative flex h-3.5 gap-0.5"
          role="img"
          :aria-label="`Overall level score ${overall.toFixed(2)} out of 4`"
        >
          <span
            v-for="i in 5"
            :key="i"
            class="flex-1 rounded-[2px]"
            :style="{ background: `var(--level-${i})` }"
          />
          <span
            class="bg-foreground absolute -top-1 -bottom-1 w-0.5 -translate-x-px rounded-[2px]
                   shadow-[0_0_0_2px_var(--surface-1)]"
            :style="{ left: `${overallPct}%` }"
          />
        </div>
        <p class="text-muted-foreground mt-3 mb-0 text-xs">
          The mean <Term id="level_score" /> of every lift below: 0 beginner, 2 intermediate,
          4 elite. This is where you stand against other lifters - for whether you are
          getting stronger, the <NuxtLink to="/">dashboard</NuxtLink> answers against your own
          past self.
        </p>
      </CardContent>
    </Card>

    <Card class="mb-4" :class="{ stale: pending }">
      <CardHeader>
        <CardTitle>By lift</CardTitle>
        <CardDescription>
          Best <Term id="e1rm" /> in the last year, placed on the bands for your bodyweight.
          Hover a band to see its threshold.
        </CardDescription>
      </CardHeader>
      <CardContent>
        <p v-if="entries.length === 0" class="text-muted-foreground py-7 text-center text-[13px]">
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
            <p v-if="entry.also_logged?.length" class="text-muted-foreground mt-0.5 mb-0 text-xs">
              Also logged against this standard, and weaker:
              {{ entry.also_logged.join(', ') }}
            </p>
          </StandardsRow>
        </div>
      </CardContent>
    </Card>

    <Card v-if="entries.length" class="mb-4">
      <CardHeader>
        <CardTitle>Thresholds</CardTitle>
        <CardDescription>
          The same numbers as a table - kilograms required at each level for your bodyweight.
        </CardDescription>
      </CardHeader>
      <CardContent>
        <div class="overflow-x-auto">
          <Table class="numeric-table">
            <TableHeader>
              <TableRow>
                <TableHead>Exercise</TableHead>
                <TableHead><Term id="e1rm" capitalize /> ({{ unit }})</TableHead>
                <TableHead>Beginner</TableHead>
                <TableHead>Novice</TableHead>
                <TableHead>Intermediate</TableHead>
                <TableHead>Advanced</TableHead>
                <TableHead>Elite</TableHead>
                <TableHead>Last done</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              <TableRow v-for="entry in entries" :key="entry.template_id">
                <TableCell>{{ entry.title }}</TableCell>
                <TableCell><strong>{{ amount(entry.score.e1rm_kg) }}</strong></TableCell>
                <TableCell>{{ amount(entry.score.thresholds.beginner) }}</TableCell>
                <TableCell>{{ amount(entry.score.thresholds.novice) }}</TableCell>
                <TableCell>{{ amount(entry.score.thresholds.intermediate) }}</TableCell>
                <TableCell>{{ amount(entry.score.thresholds.advanced) }}</TableCell>
                <TableCell>{{ amount(entry.score.thresholds.elite) }}</TableCell>
                <TableCell>{{ fullDate(entry.last_performed) }}</TableCell>
              </TableRow>
            </TableBody>
          </Table>
        </div>
        <p class="text-muted-foreground mt-3 mb-0 text-xs">
          Standards from
          <a href="https://strengthlevel.com/strength-standards" target="_blank" rel="noopener">
            strengthlevel.com
          </a>, interpolated to your exact bodyweight. The band names are
          <Term id="percentile" />s of lifts logged on that site - beginner is the 5th, novice
          the 20th, intermediate the 50th, advanced the 80th, elite the 95th - so they rank you
          against people who track their training, not against the general population.
        </p>
      </CardContent>
    </Card>

    <Card v-if="(report?.unmapped ?? []).length" class="mb-4">
      <CardHeader>
        <CardTitle>Not benchmarked</CardTitle>
        <CardDescription>
          No published load standard matches these. Bodyweight and timed movements -
          sit-ups, planks, hanging leg raises - have rep and time standards only, so there
          is nothing to score a load against. If one of these <em>is</em> a load exercise,
          add a rule to
          <code class="bg-background rounded px-1.5 py-0.5 text-[11px]">backend/src/hevy_coach/data/exercise_map.json</code>.
        </CardDescription>
      </CardHeader>
      <CardContent>
        <ul class="text-muted-foreground m-0 columns-2 pl-[18px] text-xs">
          <li v-for="item in report?.unmapped ?? []" :key="item.template_id">
            {{ item.title }} <span class="text-subtle">({{ item.sessions }} sessions)</span>
          </li>
        </ul>
      </CardContent>
    </Card>
  </div>
</template>
