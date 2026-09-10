<script setup lang="ts">
/**
 * Your total, its DOTS score, and what the next DOTS marker costs.
 *
 * Its own page because it is only meaningful for a goal judged on a total, and
 * because a lifter who cares about a total cares about it more than about
 * anything else on the strength page. The nav offers it only when the goal
 * tracks one; a hypertrophy log has no main lifts to add up, so arriving here
 * on that goal gets an explanation rather than a zero.
 */
import { computed } from 'vue'
import type { Profile, TotalReport } from '~/types/api'
import { fullDate, titleCase } from '~/utils/format'

const { unit, amount, weight } = useUnits()

const { data: profile } = await useFetch<Profile>('/api/profile', { key: 'profile' })
const { data: total, pending } = await useFetch<TotalReport>('/api/total', {
  query: { days: 365 },
})

const hasTotal = computed(() => Boolean(total.value?.tracks_total && total.value.total_kg > 0))

/** True when the goal totals something other than the three DOTS is scored on -
 *  general strength and its overhead press. */
const totalIsWiderThanDots = computed(
  () => total.value?.dots_total_kg != null && total.value.total_kg > total.value.dots_total_kg,
)

const milestone = computed(() => total.value?.milestone ?? null)

/** Shared by the several notes under each number: all of them are the same
 *  small print, and all of them wrap at the same measure. */
const CAVEAT = 'text-muted-foreground mt-3.5 mb-0 max-w-[76ch] text-xs leading-normal'

const VERDICT_COLOUR: Record<string, string> = {
  lagging: 'text-serious',
  leading: 'text-success',
}
</script>

<template>
  <div>
    <div class="mb-[18px] flex flex-wrap items-baseline justify-between gap-4">
      <h1>Your total</h1>
      <p v-if="total && hasTotal" class="text-muted-foreground m-0 text-[13px]">
        {{ titleCase(total.goal) }} goal &middot; {{ titleCase(total.sex) }} &middot;
        {{ weight(total.bodyweight_kg) }}
      </p>
    </div>

    <!-- Reached by URL on a goal with no total, or before anything is logged. -->
    <Card v-if="!hasTotal">
      <CardContent class="px-6 py-9 text-center">
        <h2>No total for this goal</h2>
        <p class="text-muted-foreground mx-auto mt-2.5 max-w-[52ch] text-[13px]">
          <template v-if="profile && !profile.tracks_total">
            Your training goal is <strong>{{ titleCase(profile.training_goal) }}</strong>, which
            is judged on weekly volume per muscle group rather than on a total. Choose
            <strong>Strength</strong> or <strong>Powerlifting</strong> in
            <NuxtLink to="/settings">Settings</NuxtLink> and this page fills in.
          </template>
          <template v-else>
            Nothing to add up yet. Import a Hevy CSV export on the
            <NuxtLink to="/">dashboard</NuxtLink> and log the main lifts.
          </template>
        </p>
      </CardContent>
    </Card>

    <template v-else-if="total">
      <Card class="mb-4" :class="{ stale: pending }">
        <CardContent>
          <div class="flex flex-wrap gap-10">
            <div>
              <span class="text-muted-foreground text-xs"><Term id="total" capitalize /></span>
              <p class="mt-0.5 mb-0 text-[40px] leading-[1.05] font-semibold tracking-[-0.02em] tabular-nums">
                {{ amount(total.total_kg, 0) }}<span
                  class="text-muted-foreground ml-1.5 text-sm tracking-normal"
                >{{ unit }}</span>
              </p>
              <p class="text-subtle mt-1.5 mb-0 max-w-[42ch] text-xs">
                {{ total.entries.length }} lifts:
                {{ total.entries.map((entry) => titleCase(entry.lift)).join(' + ') }}
              </p>
            </div>
            <div v-if="total.dots !== null">
              <span class="text-muted-foreground text-xs"><Term id="dots" capitalize /></span>
              <p class="mt-0.5 mb-0 text-[40px] leading-[1.05] font-semibold tracking-[-0.02em] tabular-nums">
                {{ total.dots }}
              </p>
              <p class="text-subtle mt-1.5 mb-0 max-w-[42ch] text-xs">
                <template v-if="totalIsWiderThanDots">
                  From {{ amount(total.dots_total_kg, 0) }} {{ unit }} of squat, bench and
                  deadlift only - the total DOTS is built for.
                </template>
                <template v-else>Bodyweight-adjusted; ~400 is a strong raw lifter.</template>
              </p>
            </div>
          </div>

          <p :class="CAVEAT">
            This is a <strong>training</strong> total, not a meet result. Every lift in it is an
            <Term id="e1rm" /> off your working sets, which reads higher than a single on the
            platform on the day - so treat it as "where my training is now".
          </p>

          <p v-if="total.dots_missing.length" :class="CAVEAT">
            No DOTS score:
            {{ total.dots_missing.map((lift) => titleCase(lift)).join(' and ') }}
            {{ total.dots_missing.length === 1 ? 'is' : 'are' }} not in the log, and a partial
            total would flatter.
          </p>
          <p v-else-if="total.bodyweight_clamped" :class="CAVEAT">
            Your bodyweight sits outside the range the DOTS formula was fitted on, so it was
            clamped to the edge of that range.
          </p>
          <p v-if="total.missing.length" :class="CAVEAT">
            Missing from the total:
            {{ total.missing.map((lift) => titleCase(lift)).join(', ') }} - never logged, so
            {{ total.missing.length === 1 ? 'it counts' : 'they count' }} as nothing.
          </p>
        </CardContent>
      </Card>

      <Card v-if="milestone" class="border-l-primary mb-4 border-l-[3px]">
        <CardHeader>
          <CardTitle>Breaking down your next milestone</CardTitle>
          <CardAction>
            <span
              class="bg-primary text-primary-foreground rounded-full px-2.5 py-0.5 text-[11px]
                     font-medium whitespace-nowrap"
            >{{ milestone.dots }} DOTS</span>
          </CardAction>
          <CardDescription>
            <template v-if="milestone.near_dots !== null">
              You are <strong>{{ amount(milestone.near_add_total_kg) }} {{ unit }}</strong> off
              {{ milestone.near_dots }} DOTS - near enough that it is not worth a plan. The next
              marker worth aiming at is <strong>{{ milestone.dots }}</strong>, which needs
              {{ amount(milestone.total_kg, 0) }} {{ unit }}.
            </template>
            <template v-else>
              {{ milestone.dots }} DOTS needs a total of
              <strong>{{ amount(milestone.total_kg, 0) }} {{ unit }}</strong>.
            </template>
            To add that <strong>{{ amount(milestone.add_total_kg, 0) }} {{ unit }}</strong>, each
            lift owes the share it already contributes - the same percentage from all three:
          </CardDescription>
        </CardHeader>
        <CardContent>
          <ul class="m-0 mt-1 flex list-none flex-col gap-2 p-0">
            <li
              v-for="lift in milestone.lifts"
              :key="lift.lift"
              class="bg-background flex flex-wrap items-baseline gap-3 rounded-lg border px-3 py-2.5"
            >
              <span class="min-w-[9rem] font-medium">{{ titleCase(lift.lift) }}</span>
              <span class="min-w-[6rem] text-[19px] font-semibold tracking-[-0.01em] tabular-nums">
                +{{ amount(lift.add_kg) }} {{ unit }}
              </span>
              <span class="text-subtle text-xs tabular-nums">
                {{ amount(lift.e1rm_kg) }} &rarr; {{ amount(lift.target_kg) }} {{ unit }}
              </span>
            </li>
          </ul>

          <p :class="CAVEAT">
            Those three jumps land you on {{ amount(milestone.reaches_total_kg, 0) }} {{ unit }},
            which scores
            <strong v-if="milestone.reaches_dots !== null">{{ milestone.reaches_dots }}</strong>
            DOTS - targets are snapped to 2.5 {{ unit }} jumps, so the route clears the marker
            rather than landing just short. Splitting it proportionally is arithmetic, not
            coaching: pushing a lagging lift harder is a real strategy, and the ratios below
            are where this app says anything about that.
          </p>
        </CardContent>
      </Card>

      <Card class="mb-4">
        <CardHeader>
          <CardTitle>Where the total comes from</CardTitle>
          <CardDescription>Best <Term id="e1rm" /> per lift in the last year.</CardDescription>
        </CardHeader>
        <CardContent>
          <div class="overflow-x-auto">
            <Table class="numeric-table">
              <TableHeader>
                <TableRow>
                  <TableHead>Lift</TableHead>
                  <TableHead class="text-left!">Logged as</TableHead>
                  <TableHead><Term id="e1rm" capitalize /> ({{ unit }})</TableHead>
                  <TableHead>Share</TableHead>
                  <TableHead>Sessions</TableHead>
                  <TableHead>Last done</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                <TableRow v-for="entry in total.entries" :key="entry.lift">
                  <TableCell>{{ titleCase(entry.lift) }}</TableCell>
                  <TableCell class="text-subtle text-left!">{{ entry.title }}</TableCell>
                  <TableCell><strong>{{ amount(entry.e1rm_kg) }}</strong></TableCell>
                  <TableCell>{{ entry.share.toFixed(0) }}%</TableCell>
                  <TableCell>{{ entry.sessions }}</TableCell>
                  <TableCell>{{ fullDate(entry.last_performed) }}</TableCell>
                </TableRow>
              </TableBody>
            </Table>
          </div>
        </CardContent>
      </Card>

      <Card v-if="total.ratios.length">
        <CardHeader>
          <CardTitle>How the lifts sit together</CardTitle>
          <CardDescription>
            Against the squat, with wide tolerances - these catch a lift that is genuinely
            lagging, not unusual leverages.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <ul class="text-muted-foreground m-0 list-disc pl-[18px] text-xs">
            <li v-for="ratio in total.ratios" :key="ratio.lift" class="[&+li]:mt-1">
              {{ ratio.title }} is <strong>{{ ratio.ratio.toFixed(2) }}x</strong> your squat,
              against {{ ratio.expected.toFixed(2) }}x for a typical raw lifter -
              <span :class="VERDICT_COLOUR[ratio.verdict]">{{ ratio.verdict }}</span>.
            </li>
          </ul>
        </CardContent>
      </Card>
    </template>
  </div>
</template>
