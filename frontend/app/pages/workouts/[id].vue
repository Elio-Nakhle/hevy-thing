<script setup lang="ts">
/**
 * One session: what it did to each lift, and what to load the next time this
 * routine comes round.
 *
 * The plan card is deliberately first and deliberately terse - it is the part
 * you read standing in front of a rack. Everything below it is the evidence for
 * the plan, in the order you would want to argue with it: what you actually
 * did, how it compared to last time, and why the model chose what it chose.
 */
import { computed } from 'vue'
import { useRoute } from 'vue-router'
import type { ExerciseBlock, SessionAction, WorkoutDetail } from '~/types/api'
import { fullDate, titleCase } from '~/utils/format'

const { unit, amount, weight } = useUnits()

const route = useRoute()
const workoutId = computed(() => String(route.params.id))

const { data: detail, error } = await useFetch<WorkoutDetail>(
  () => `/api/workouts/${workoutId.value}`,
)

/** Colour and wording per progression decision. Colour never carries meaning
 *  alone - every chip is labelled, and the reasoning sits beside it. */
const ACTIONS: Record<SessionAction, { label: string; color: string }> = {
  add_load: { label: 'Add load', color: 'var(--success-text)' },
  add_reps: { label: 'Add reps', color: 'var(--series-1)' },
  hold: { label: 'Hold', color: 'var(--warning)' },
  deload: { label: 'Deload', color: 'var(--critical)' },
  establish: { label: 'Baseline', color: 'var(--text-secondary)' },
  no_basis: { label: 'Not scored', color: 'var(--text-muted)' },
}

/** "3 x 8 @ 62.5 kg", built from the numeric fields so it honours kg/lb. */
function prescription(block: ExerciseBlock): string {
  const rec = block.recommendation
  if (rec.target_sets === null || rec.target_reps === null) return '-'
  const load = rec.target_weight_kg ? weight(rec.target_weight_kg) : 'bodyweight'
  return `${rec.target_sets} × ${rec.target_reps} @ ${load}`
}

/** What was actually done on the top sets: "2 × 8 @ 25 kg". */
function performed(block: ExerciseBlock): string {
  const top = block.sets.filter((set) => set.is_top)
  if (top.length === 0) return '-'
  const reps = [...new Set(top.map((set) => set.reps))].join('/')
  const load = block.top_weight_kg ? weight(block.top_weight_kg) : 'bodyweight'
  return `${top.length} × ${reps} @ ${load}`
}

function ramp(block: ExerciseBlock): string {
  const up = block.sets.filter((set) => !set.is_top)
  return up.map((set) => `${amount(set.weight_kg, 0)}×${set.reps}`).join(', ')
}

const planned = computed(() =>
  (detail.value?.exercises ?? []).filter((b) => b.recommendation.action !== 'no_basis'),
)

const prs = computed(() => (detail.value?.exercises ?? []).filter((b) => b.is_pr).length)

/* The progression-decision chip: label plus a dot, repeated in the plan table
 * and again on every exercise block. */
const CHIP = 'inline-flex items-center gap-1.5 text-xs whitespace-nowrap'

/* The small upper-case heading on each side panel. */
const PANEL_HEAD = 'text-subtle m-0 mb-1.5 text-[11px] font-medium tracking-[0.04em] uppercase'

const maxMuscleSets = computed(() =>
  Math.max(1, ...(detail.value?.muscle_groups ?? []).map((g) => g.sets)),
)
</script>

<template>
  <div>
    <Card v-if="error">
      <CardContent>
        <p class="text-muted-foreground py-7 text-center text-[13px]">No session with that id.</p>
      </CardContent>
    </Card>

    <template v-else-if="detail">
      <div class="mb-[18px]">
        <NuxtLink
          to="/workouts"
          class="text-muted-foreground mb-1 inline-block text-xs no-underline hover:underline hover:underline-offset-[3px]"
        >
          &larr; Workouts
        </NuxtLink>
        <h1>{{ detail.title }}</h1>
        <p class="text-muted-foreground mt-1 mb-0 text-[13px]">
          {{ fullDate(detail.start_time) }} &middot;
          run {{ detail.routine.run_index }} of {{ detail.routine.runs }}
          <template v-if="detail.routine.runs > 1"> of this routine</template>
          <!-- Run-to-run tonnage swings wildly with which accessories made the
               cut, so the routine's own median is the steadier reference. -->
          <template v-if="detail.routine.runs > 2 && detail.routine.median_volume_kg">
            &middot; typical run is
            {{ amount(detail.routine.median_volume_kg, 0) }} {{ unit }}
          </template>
        </p>
      </div>

      <div class="mb-4 grid gap-4 md:grid-cols-4">
        <StatTile
          :value="amount(detail.volume_kg, 0)"
          :unit="unit"
          :delta="detail.routine.volume_delta_pct"
          delta-label="vs previous run"
        >
          <template #label><Term id="volume" capitalize /></template>
        </StatTile>
        <StatTile :value="String(detail.sets)">
          <template #label><Term id="working_set" capitalize />s</template>
        </StatTile>
        <StatTile
          label="Duration"
          :value="detail.duration_minutes ? String(Math.round(detail.duration_minutes)) : '-'"
          unit="min"
        />
        <StatTile label="Lifetime bests" :value="String(prs)" />
      </div>

      <Card v-if="detail.notes.length" class="mb-4">
        <CardHeader>
          <CardTitle>Worth knowing</CardTitle>
        </CardHeader>
        <CardContent>
          <ul class="text-muted-foreground m-0 list-disc pl-[18px] text-[13px]">
            <li v-for="note in detail.notes" :key="note" class="[&+li]:mt-1">{{ note }}</li>
          </ul>
        </CardContent>
      </Card>

      <!-- The plan. First, because it is the reason to open this page. -->
      <Card class="mb-6">
        <CardHeader>
          <CardTitle>Next time you run {{ detail.title }}</CardTitle>
          <CardDescription>
            <Term id="prescription" capitalize />: hold the load until every
            <Term id="working_set" /> reaches the top of its <Term id="rep_range" />, then add
            the <Term id="load_step" /> your history shows you actually use and drop back to
            the bottom of the range. <NuxtLink to="/next">Take it to the rack</NuxtLink>.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <p v-if="planned.length === 0" class="text-muted-foreground py-7 text-center text-[13px]">
            Nothing here can be progressed - no session had both a load and a rep count.
          </p>
          <div v-else class="overflow-x-auto">
            <Table class="numeric-table">
              <TableHeader>
                <TableRow>
                  <TableHead>Exercise</TableHead>
                  <TableHead>This session</TableHead>
                  <TableHead>Next target</TableHead>
                  <TableHead>Range</TableHead>
                  <TableHead class="text-left!">Call</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                <TableRow v-for="block in planned" :key="block.template_id">
                  <TableCell class="text-left!">
                    <NuxtLink
                      :to="`/exercises/${block.template_id}`"
                      class="no-underline hover:underline hover:underline-offset-[3px]"
                    >
                      {{ block.title }}
                    </NuxtLink>
                  </TableCell>
                  <TableCell>{{ performed(block) }}</TableCell>
                  <TableCell class="font-semibold">{{ prescription(block) }}</TableCell>
                  <TableCell class="text-subtle">
                    <template v-if="block.recommendation.rep_range">
                      {{ block.recommendation.rep_range[0] }}-{{ block.recommendation.rep_range[1] }}
                    </template>
                    <span v-else>-</span>
                  </TableCell>
                  <TableCell class="text-left!">
                    <span
                      :class="CHIP"
                      :style="{ color: ACTIONS[block.recommendation.action].color }"
                    >
                      <span
                        class="inline-block size-2 rounded-full"
                        :style="{ background: ACTIONS[block.recommendation.action].color }"
                      />
                      {{ ACTIONS[block.recommendation.action].label }}
                    </span>
                  </TableCell>
                </TableRow>
              </TableBody>
            </Table>
          </div>
        </CardContent>
      </Card>

      <!-- The evidence, exercise by exercise. -->
      <h2 class="text-muted-foreground mb-2.5 text-[13px] tracking-[0.04em] uppercase">
        Session detail
      </h2>
      <Card v-for="block in detail.exercises" :key="block.template_id" class="mb-3">
        <CardContent>
          <div class="mb-3 flex items-start justify-between gap-3">
            <div>
              <h3 class="flex flex-wrap items-center gap-2">
                <NuxtLink
                  :to="`/exercises/${block.template_id}`"
                  class="no-underline hover:underline hover:underline-offset-[3px]"
                >
                  {{ block.title }}
                </NuxtLink>
                <span
                  v-if="block.is_pr"
                  class="text-success rounded-[5px] border border-current px-1.5 py-px text-[10px]
                         font-medium tracking-[0.04em] uppercase"
                >best <Term id="e1rm" /></span>
              </h3>
              <p class="text-muted-foreground mt-0.5 mb-0 text-xs">
                <template v-if="block.muscle_group">{{ titleCase(block.muscle_group) }} &middot; </template>
                {{ block.working_sets }} sets &middot;
                {{ amount(block.volume_kg, 0) }} {{ unit }} &middot;
                session {{ block.sessions }} on this lift
              </p>
            </div>
            <span :class="CHIP" :style="{ color: ACTIONS[block.recommendation.action].color }">
              <span
                class="inline-block size-2 rounded-full"
                :style="{ background: ACTIONS[block.recommendation.action].color }"
              />
              {{ ACTIONS[block.recommendation.action].label }}
            </span>
          </div>

          <div class="grid gap-[18px] min-[800px]:grid-cols-[minmax(0,5fr)_minmax(0,7fr)]">
            <div>
              <Table class="numeric-table">
                <TableHeader>
                  <TableRow>
                    <TableHead>Set</TableHead>
                    <TableHead>Load ({{ unit }})</TableHead>
                    <TableHead>Reps</TableHead>
                    <TableHead><Term id="e1rm" capitalize /> ({{ unit }})</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  <TableRow
                    v-for="set in block.sets"
                    :key="set.set_index"
                    :class="{ 'text-subtle': !set.is_top }"
                  >
                    <TableCell>
                      {{ set.set_index + 1 }}
                      <span v-if="!set.is_top" class="text-subtle"> <Term id="ramp_up" /></span>
                    </TableCell>
                    <TableCell>
                      <template v-if="set.weight_kg !== null">{{ amount(set.weight_kg) }}</template>
                      <span v-else class="text-subtle">bw</span>
                    </TableCell>
                    <TableCell>{{ set.reps ?? '-' }}</TableCell>
                    <TableCell>{{ set.e1rm_kg !== null ? amount(set.e1rm_kg) : '-' }}</TableCell>
                  </TableRow>
                </TableBody>
              </Table>
            </div>

            <div class="flex flex-col gap-3.5">
              <div v-if="block.previous">
                <h4 :class="PANEL_HEAD">Against {{ fullDate(block.previous.date) }}</h4>
                <dl class="m-0 flex flex-wrap gap-5 text-[13px]">
                  <div>
                    <dt class="text-muted-foreground text-[11px]">Top set</dt>
                    <dd class="m-0 tabular-nums">
                      {{ block.previous.top_set_count }} ×
                      {{ block.previous.top_reps }} @
                      {{ block.previous.top_weight_kg ? weight(block.previous.top_weight_kg) : 'bw' }}
                    </dd>
                  </div>
                  <div>
                    <dt class="text-muted-foreground text-[11px]"><Term id="e1rm" capitalize /></dt>
                    <dd
                      class="m-0 tabular-nums"
                      :style="{ color: (block.e1rm_delta_kg ?? 0) >= 0 ? 'var(--success-text)' : 'var(--critical)' }"
                    >
                      <template v-if="block.e1rm_delta_kg !== null">
                        {{ block.e1rm_delta_kg >= 0 ? '+' : '' }}{{ amount(block.e1rm_delta_kg) }} {{ unit }}
                      </template>
                      <span v-else class="text-subtle">-</span>
                    </dd>
                  </div>
                  <div>
                    <dt class="text-muted-foreground text-[11px]"><Term id="volume" capitalize /></dt>
                    <dd class="m-0 tabular-nums">
                      <template v-if="block.volume_delta_pct !== null">
                        {{ block.volume_delta_pct >= 0 ? '+' : '' }}{{ block.volume_delta_pct.toFixed(0) }}%
                      </template>
                      <span v-else class="text-subtle">-</span>
                    </dd>
                  </div>
                </dl>
              </div>
              <p v-else class="text-muted-foreground m-0 text-xs">
                First time this exercise appears in the log.
              </p>

              <div class="border-primary border-l-2 pl-3">
                <h4 :class="PANEL_HEAD">Next time</h4>
                <p class="m-0 text-base font-semibold tracking-[-0.01em] tabular-nums">
                  {{ prescription(block) }}
                </p>
                <p class="text-muted-foreground mt-1.5 mb-0 text-xs leading-normal">
                  {{ block.recommendation.detail }}
                </p>
                <p v-if="ramp(block)" class="text-muted-foreground mt-1.5 mb-0 text-xs leading-normal">
                  <Term id="ramp_up" capitalize />s ({{ ramp(block) }}) are reported but left
                  out of the decision - only the sets at the top load drive it.
                </p>
              </div>
            </div>
          </div>
        </CardContent>
      </Card>

      <Card v-if="detail.muscle_groups.length">
        <CardHeader>
          <CardTitle>What this session trained</CardTitle>
          <CardDescription>
            Working sets by primary muscle group. Single-session counts, so read them against
            your weekly targets on the dashboard rather than on their own.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <ul class="m-0 list-none p-0 text-xs">
            <li
              v-for="group in detail.muscle_groups"
              :key="group.muscle_group"
              class="grid grid-cols-[110px_minmax(0,1fr)_32px] items-center gap-2.5 py-[3px]"
            >
              <span>{{ titleCase(group.muscle_group) }}</span>
              <span class="bg-gridline h-2.5 overflow-hidden rounded-[3px]">
                <span
                  class="bg-primary block h-full"
                  :style="{ width: `${(group.sets / maxMuscleSets) * 100}%` }"
                />
              </span>
              <span class="text-muted-foreground text-right tabular-nums">{{ group.sets }}</span>
            </li>
          </ul>
        </CardContent>
      </Card>
    </template>
  </div>
</template>
