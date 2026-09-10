<script setup lang="ts">
/**
 * The rack view: what to do in your next session, on a phone.
 *
 * The prescriptions themselves are not new - `session.py` has computed them
 * since the beginning, buried at the bottom of a workout-detail page you could
 * only reach on a laptop, after training. Every participant in the roadmap's
 * research rated them the most useful thing in the app and none of them could
 * get to them at the point of use.
 *
 * So this page is deliberately thin: one column, big type, no charts. It states
 * each prescription's reasoning inline rather than in a tooltip, because native
 * tooltips do not open on touch.
 *
 * The one thing it writes is which routines are in the rotation. Trying five
 * routines is not committing to five, and a Hevy log accumulates titles faster
 * than it accumulates programmes - so the switcher offers the current rotation
 * and keeps the rest one tap away, with the lifter able to put a routine away
 * for good when the date heuristics cannot know they are finished with it.
 */
import { computed, ref } from 'vue'
import type {
  NextSession,
  NextSessionExercise,
  Recommendation,
  RoutineDue,
  SessionAction,
} from '~/types/api'
import { fullDate, titleCase } from '~/utils/format'

const { weight } = useUnits()

/** Which routine to show. Empty means "whichever is due". */
const routine = ref('')
const showOthers = ref(false)
const busy = ref(false)

const { data: session, pending, error } = await useFetch<NextSession>('/api/next-session', {
  query: computed(() => (routine.value ? { routine: routine.value } : {})),
})

/** The current rotation, which is what the switcher offers up front. */
const rotation = computed(() => (session.value?.alternatives ?? []).filter((r) => r.active))

/** Everything else: tried once, long abandoned, or explicitly put away. Kept
 *  reachable because "not in the rotation" is not the same as "never again". */
const others = computed(() => (session.value?.alternatives ?? []).filter((r) => !r.active))

/** Whichever routine is on screen, even if it is not in the rotation. */
const shown = computed(() => session.value?.routine.title ?? '')

async function setDismissed(item: RoutineDue, dismissed: boolean) {
  busy.value = true
  try {
    await $fetch('/api/routines/dismissed', {
      method: 'PUT',
      body: { title: item.title, dismissed },
    })
    // Putting away what is on screen means the app should move off it.
    if (dismissed && item.title === shown.value) routine.value = ''
    // Refetches this page and the dashboard headline, which names what is due.
    await refreshNuxtData()
  } finally {
    busy.value = false
  }
}

function select(item: RoutineDue) {
  routine.value = item.title
}

/** How each action reads at a glance. Colour carries "is this a push or a
 *  back-off", which is the only distinction that matters mid-session. */
const ACTIONS: Record<SessionAction, { label: string; colour: string }> = {
  add_load: { label: 'Add weight', colour: 'var(--good)' },
  add_reps: { label: 'Add reps', colour: 'var(--series-1)' },
  hold: { label: 'Repeat', colour: 'var(--text-muted)' },
  deload: { label: 'Back off', colour: 'var(--warning)' },
  establish: { label: 'Baseline', colour: 'var(--text-muted)' },
  no_basis: { label: 'No target', colour: 'var(--text-muted)' },
}

function action(item: Recommendation) {
  return ACTIONS[item.action] ?? ACTIONS.no_basis
}

/** Built from the numeric fields rather than `headline`, so a lifter who reads
 *  in pounds gets pounds. */
function prescription(item: Recommendation): string {
  if (item.target_sets === null || item.target_reps === null) return item.headline
  const load = item.target_weight_kg ? weight(item.target_weight_kg) : 'bodyweight'
  return `${item.target_sets} × ${item.target_reps} @ ${load}`
}

/**
 * What you actually did, set by set.
 *
 * Every set rather than the best one: the prescription progresses the *worst*
 * set at the top load, so "2 × 12" beside a target of 11 reads as a downgrade
 * when the truth was a 12 and a 10.
 */
function lastTime(exercise: NextSessionExercise): string | null {
  const reps = exercise.last_top_set_reps
  if (reps.length === 0) return null
  const load = exercise.last_top_weight_kg ? weight(exercise.last_top_weight_kg) : 'bodyweight'
  const uniform = reps.every((count) => count === reps[0])
  const scheme = uniform ? `${reps.length} × ${reps[0]}` : reps.join(', ')
  return `${scheme} @ ${load}`
}

/** The weight change from last time, when there is one worth showing. */
function loadDelta(exercise: NextSessionExercise): string | null {
  const target = exercise.recommendation.target_weight_kg
  const last = exercise.last_top_weight_kg
  if (target === null || last === null || Math.abs(target - last) < 0.01) return null
  const sign = target > last ? '+' : '−'
  return `${sign}${weight(Math.abs(target - last))}`
}

function routineLabel(title: string): string {
  return title.trim() || 'Untitled'
}

/* The rotation chips, as one string: three call sites want the same pill, and
 * 44px is the smallest thing a thumb hits reliably. Pressed state rides on
 * `aria-pressed`, so the styling and the accessible state cannot drift apart. */
const CHIP = 'inline-flex min-h-11 cursor-pointer items-center gap-1.5 rounded-full border '
  + 'bg-card text-muted-foreground px-3.5 text-[13px] '
  + 'aria-pressed:border-primary aria-pressed:text-foreground aria-pressed:font-medium '
  + 'aria-pressed:bg-[color-mix(in_srgb,var(--series-1)_8%,var(--surface-1))]'

/* The chip and its put-away button read as one control, so the pair joins in
 * the middle and only the outer edges are round. */
const CHIP_JOINED = `${CHIP} rounded-r-none border-r-0`

const CHIP_SIDE = 'min-h-11 cursor-pointer rounded-r-full border bg-card px-2.5 text-[15px] '
  + 'leading-none text-subtle hover:border-baseline hover:text-foreground '
  + 'disabled:cursor-default disabled:opacity-50'

function daysAgo(days: number): string {
  if (days === 0) return 'today'
  if (days === 1) return 'yesterday'
  return `${days} days ago`
}
</script>

<template>
  <!-- One column, thumb-width, regardless of the screen it lands on. -->
  <div class="mx-auto max-w-[30rem]">
    <Card v-if="error">
      <CardContent class="px-6 py-10 text-center">
        <h1>Nothing to prescribe yet</h1>
        <p class="text-muted-foreground mx-auto mt-2.5 max-w-[34ch] text-[13px]">
          Import a Hevy CSV export on the <NuxtLink to="/">dashboard</NuxtLink> and this fills
          in with your next session.
        </p>
      </CardContent>
    </Card>

    <template v-else-if="session">
      <header class="mb-4">
        <span class="text-muted-foreground text-xs font-medium tracking-[0.06em] uppercase">
          Next session
        </span>
        <h1 class="mt-0.5 text-[28px]">{{ routineLabel(session.routine.title) }}</h1>
        <p class="text-muted-foreground mt-1 mb-0 text-xs">
          Last run {{ daysAgo(session.routine.days_since) }}
          ({{ fullDate(session.routine.last_performed) }}) &middot;
          run {{ session.routine.runs }} of this routine
        </p>
      </header>

      <div v-if="rotation.length > 1 || others.length" class="mb-4 flex flex-wrap gap-2">
        <span v-for="option in rotation" :key="option.title" class="inline-flex items-stretch">
          <button
            type="button"
            :class="CHIP_JOINED"
            :aria-pressed="option.title === shown"
            @click="select(option)"
          >
            {{ routineLabel(option.title) }}
            <span class="text-subtle text-[11px] tabular-nums">{{ option.days_since }}d</span>
          </button>
          <button
            type="button"
            :class="CHIP_SIDE"
            :disabled="busy"
            :title="`Take ${routineLabel(option.title)} out of the rotation`"
            :aria-label="`Take ${routineLabel(option.title)} out of the rotation`"
            @click="setDismissed(option, true)"
          >&times;</button>
        </span>

        <button
          v-if="others.length"
          type="button"
          :class="[CHIP, 'border-dashed']"
          :aria-expanded="showOthers"
          @click="showOthers = !showOthers"
        >
          {{ showOthers ? 'Hide' : `${others.length} not in your rotation` }}
        </button>
      </div>

      <div v-if="showOthers && others.length" class="mt-[-6px] mb-4 flex flex-wrap gap-2">
        <p class="text-subtle m-0 mb-0.5 basis-full text-xs leading-normal">
          Routines you have run once, or not in the last four weeks, or put away. They are
          not offered or predicted - tap one to use it anyway.
        </p>
        <span v-for="option in others" :key="option.title" class="inline-flex items-stretch">
          <button
            type="button"
            :class="[CHIP_JOINED, 'border-dashed']"
            :aria-pressed="option.title === shown"
            @click="select(option)"
          >
            {{ routineLabel(option.title) }}
            <span class="text-subtle text-[11px] tabular-nums">
              {{ option.runs === 1 ? 'once' : `${option.runs} runs` }} &middot;
              {{ option.days_since }}d
            </span>
          </button>
          <button
            type="button"
            :class="CHIP_SIDE"
            :disabled="busy"
            :title="option.dismissed
              ? `Put ${routineLabel(option.title)} back in the rotation`
              : `Put ${routineLabel(option.title)} away`"
            :aria-label="option.dismissed
              ? `Put ${routineLabel(option.title)} back in the rotation`
              : `Put ${routineLabel(option.title)} away`"
            @click="setDismissed(option, !option.dismissed)"
          >{{ option.dismissed ? '+' : '×' }}</button>
        </span>
      </div>

      <p class="mt-0 mb-4 text-[15px] leading-[1.4] font-medium" :class="{ stale: pending }">
        {{ session.summary }}
      </p>

      <ol class="m-0 flex list-none flex-col gap-3 p-0" :class="{ stale: pending }">
        <li v-for="exercise in session.exercises" :key="exercise.template_id">
          <Card>
            <CardContent>
              <div class="flex items-start justify-between gap-2.5">
                <h2 class="text-base leading-[1.3]">{{ exercise.title }}</h2>
                <span
                  class="shrink-0 rounded-full px-2 py-0.5 text-[11px] font-medium whitespace-nowrap text-white"
                  :style="{ background: action(exercise.recommendation).colour }"
                >{{ action(exercise.recommendation).label }}</span>
              </div>

              <p v-if="exercise.muscle_group" class="text-subtle mt-0.5 mb-0 text-xs">
                {{ titleCase(exercise.muscle_group) }}
              </p>

              <!-- The number you are standing there to read. -->
              <p class="mt-3 mb-0 flex flex-wrap items-baseline gap-2.5 text-[26px] font-semibold tracking-[-0.02em] tabular-nums">
                {{ prescription(exercise.recommendation) }}
                <span
                  v-if="loadDelta(exercise)"
                  class="text-muted-foreground text-[13px] font-medium tracking-normal"
                >{{ loadDelta(exercise) }}</span>
              </p>

              <p v-if="lastTime(exercise)" class="text-muted-foreground mt-1.5 mb-0 text-[13px] tabular-nums">
                Last time: {{ lastTime(exercise) }}
              </p>

              <p class="text-subtle mt-2.5 mb-0 text-xs leading-normal">
                {{ exercise.recommendation.detail }}
              </p>
            </CardContent>
          </Card>
        </li>
      </ol>

      <p class="text-subtle mt-5 mb-0 text-[11px] leading-normal">
        Prescriptions use double progression: hold the weight until you reach the top of the
        rep range on every working set, then add the smallest jump this exercise moves in and
        drop back to the bottom. Read-only - nothing here is logged back to Hevy.
      </p>
    </template>
  </div>
</template>
