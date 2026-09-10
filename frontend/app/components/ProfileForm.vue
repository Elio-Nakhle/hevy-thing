<script setup lang="ts">
/**
 * The lifter profile: bodyweight, sex, birth date, units, dumbbell convention
 * and training goal.
 *
 * These few values decide what most of the analysis *says* - every strength
 * standard is indexed on bodyweight and sex, and every volume threshold comes
 * from the goal - so the form's one hard rule is that it never presents a
 * default as an answer. An unset bodyweight starts blank and blocks the save,
 * because a placeholder the user confirmed by accident is worse than one the
 * app admits to: it silences the caveat on the strength page.
 *
 * Saving PUTs to `/api/profile`, which writes the same `.env` the CLI reads.
 */
import { computed, reactive, ref, watch } from 'vue'
import type { GoalProfile, Profile } from '~/types/api'
import { titleCase } from '~/utils/format'

const props = defineProps<{
  /** Shown on first run: leads with why we are asking rather than a bare form. */
  firstRun?: boolean
}>()

const emit = defineEmits<{ saved: [Profile] }>()

const LB_PER_KG = 2.2046226218

// The shared key means this and `useUnits` are one request, and one refresh.
const { data: profile } = await useFetch<Profile>('/api/profile', { key: 'profile' })
const { data: goals } = await useFetch<GoalProfile[]>('/api/goals', { key: 'goals' })

const form = reactive({
  sex: 'male' as Profile['sex'],
  /** In `form.units`, not kilograms. Empty string until the user gives one. */
  bodyweight: '' as string,
  units: 'kg' as Profile['units'],
  birth_date: '',
  dumbbell_load: 'per_dumbbell' as Profile['dumbbell_load'],
  training_goal: 'hypertrophy' as Profile['training_goal'],
})

const busy = ref(false)
const error = ref('')
const saved = ref(false)

/** Fields still standing on a default, so the form can say so. */
const unset = computed(() => new Set(profile.value?.unset ?? []))

function hydrate(current: Profile) {
  form.sex = current.sex
  form.units = current.units
  form.dumbbell_load = current.dumbbell_load
  form.training_goal = current.training_goal
  form.birth_date = current.birth_date ?? ''
  // A measured bodyweight is a fact about the log, not an answer to this form,
  // so the field always edits the configured number.
  form.bodyweight = current.unset.includes('bodyweight_kg')
    ? ''
    : String(round(toDisplay(current.configured_bodyweight_kg, current.units)))
}

watch(profile, (current) => current && hydrate(current), { immediate: true })

// Switching units has to move the number with the label, or "82" silently
// becomes 82 lb.
watch(
  () => form.units,
  (next, previous) => {
    if (!form.bodyweight || next === previous) return
    const kg = previous === 'lb' ? Number(form.bodyweight) / LB_PER_KG : Number(form.bodyweight)
    form.bodyweight = String(round(toDisplay(kg, next)))
  },
)

function toDisplay(kg: number, units: Profile['units']) {
  return units === 'lb' ? kg * LB_PER_KG : kg
}

function round(value: number) {
  return Math.round(value * 10) / 10
}

const bodyweightKg = computed(() => {
  const typed = Number(form.bodyweight)
  if (!form.bodyweight || !Number.isFinite(typed) || typed <= 0) return null
  return round(form.units === 'lb' ? typed / LB_PER_KG : typed)
})

/** The one required answer: everything else has a defensible default. */
const canSave = computed(() => bodyweightKg.value !== null && !busy.value)

const goalDetail = computed(
  () => goals.value?.find((goal) => goal.name === form.training_goal) ?? null,
)

/** What this goal actually changes, in the analytics' own terms. */
const goalEffects = computed(() => {
  const goal = goalDetail.value
  if (!goal) return []
  const effects: string[] = []
  effects.push(
    goal.low_weekly_sets === null
      ? 'No weekly-volume floor - accessory volume is not the thing to optimise.'
      : `Flags a muscle group under ${goal.low_weekly_sets} working sets a week.`,
  )
  if (goal.min_heavy_sets_per_week !== null) {
    effects.push(`Expects ${goal.min_heavy_sets_per_week} sets a week at 85%+ of your e1RM.`)
  }
  if (goal.min_main_lift_frequency !== null) {
    effects.push(
      `Watches ${goal.main_lifts.map((lift) => titleCase(lift)).join(', ')} for at least `
      + `${goal.min_main_lift_frequency} sessions a week each.`,
    )
  }
  if (goal.tracks_total) {
    // Name the lifts rather than saying "competition total": the general
    // strength goal totals four of them, an overhead press included.
    effects.push(
      `Totals ${goal.main_lifts.map((lift) => titleCase(lift)).join(', ')} on the strength `
      + 'page, with a DOTS score from squat, bench and deadlift.',
    )
  }
  return effects
})

async function save() {
  const kg = bodyweightKg.value
  if (kg === null) return
  busy.value = true
  error.value = ''
  saved.value = false
  try {
    const updated = await $fetch<Profile>('/api/profile', {
      method: 'PUT',
      body: {
        sex: form.sex,
        bodyweight_kg: kg,
        units: form.units,
        dumbbell_load: form.dumbbell_load,
        training_goal: form.training_goal,
        // Omitted rather than sent empty: the backend leaves out fields alone,
        // and there is no such thing as "no birth date" once one is written.
        ...(form.birth_date ? { birth_date: form.birth_date } : {}),
      },
    })
    saved.value = true
    // The goal changes which findings fire and the bodyweight rescales every
    // standard, so this invalidates far more than the profile itself.
    await refreshNuxtData()
    emit('saved', updated)
  } catch (caught: unknown) {
    const failure = caught as { data?: { detail?: unknown }; statusCode?: number }
    const detail = failure?.data?.detail
    error.value =
      typeof detail === 'string'
        ? detail
        : failure?.statusCode === 502
          ? 'Cannot reach the API - start it with `uv run hevy-coach serve`.'
          : 'Could not save. Check that the .env file is writable.'
  } finally {
    busy.value = false
  }
}
</script>

<template>
  <section class="card">
    <div class="card-head">
      <h2 class="card-title">
        {{ props.firstRun ? 'Tell us who is lifting' : 'Lifter profile' }}
      </h2>
      <span v-if="saved && !error" class="ok">Saved</span>
    </div>
    <p class="card-sub">
      <template v-if="props.firstRun">
        Your strength levels are being scored against a placeholder. Six answers fix that -
        bodyweight and sex place every lift on its band, and the goal decides which findings
        the app reports.
      </template>
      <template v-else>
        Saved to <code>{{ profile?.env_file }}</code>, which the CLI reads too.
      </template>
    </p>

    <form class="fields" @submit.prevent="save">
      <div class="field">
        <label for="bodyweight">
          Bodyweight ({{ form.units }})
          <span v-if="unset.has('bodyweight_kg')" class="flag">required</span>
        </label>
        <input
          id="bodyweight"
          v-model="form.bodyweight"
          type="number"
          inputmode="decimal"
          step="0.1"
          min="0"
          :placeholder="`Your bodyweight in ${form.units}`"
          required
        >
        <p class="hint">
          Every standard is indexed on this, so it moves whole bands.
          <template v-if="profile?.bodyweight_source === 'measured'">
            A measurement logged in Hevy outranks it.
          </template>
        </p>
      </div>

      <div class="field">
        <label for="sex">Sex</label>
        <select id="sex" v-model="form.sex">
          <option value="male">Male</option>
          <option value="female">Female</option>
        </select>
        <p class="hint">Which set of published standards your lifts are scored against.</p>
      </div>

      <div class="field">
        <label for="birth-date">Birth date <span class="flag optional">optional</span></label>
        <input id="birth-date" v-model="form.birth_date" type="date">
        <p class="hint">
          Enables the age adjustment on the standards.
          <template v-if="profile?.age"> Currently age {{ profile.age }}.</template>
        </p>
      </div>

      <div class="field">
        <label for="units">Display units</label>
        <select id="units" v-model="form.units">
          <option value="kg">Kilograms</option>
          <option value="lb">Pounds</option>
        </select>
        <p class="hint">Display only - everything is stored and calculated in kilograms.</p>
      </div>

      <div class="field span-2">
        <label for="dumbbell">Two-dumbbell loads</label>
        <select id="dumbbell" v-model="form.dumbbell_load">
          <option value="per_dumbbell">I log the weight of one dumbbell</option>
          <option value="combined">I log the pair's total</option>
        </select>
        <p class="hint">
          The standards are published per dumbbell, which is also what Hevy asks for. Get this
          wrong and every dumbbell lift is scored at double or half.
        </p>
      </div>

      <fieldset class="field span-2 goals">
        <legend>What is this log for?</legend>
        <div class="goal-options">
          <label v-for="goal in goals ?? []" :key="goal.name" class="goal">
            <input v-model="form.training_goal" type="radio" :value="goal.name">
            <span>
              <strong>{{ titleCase(goal.name) }}</strong>
              <span class="secondary goal-sub">{{ goal.summary }}</span>
            </span>
          </label>
        </div>
        <ul v-if="goalEffects.length" class="effects">
          <li v-for="(effect, i) in goalEffects" :key="i">{{ effect }}</li>
        </ul>
      </fieldset>

      <div class="actions span-2">
        <button class="btn btn-primary save" type="submit" :disabled="!canSave">
          {{ busy ? 'Saving...' : 'Save profile' }}
        </button>
        <span v-if="error" class="bad">{{ error }}</span>
        <span v-else-if="!bodyweightKg" class="secondary">
          Bodyweight is the one answer we cannot guess.
        </span>
      </div>
    </form>
  </section>
</template>

<style scoped>
.fields {
  display: grid;
  gap: 18px;
}

@media (min-width: 720px) {
  .fields {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
  .span-2 {
    grid-column: 1 / -1;
  }
}

.field {
  display: flex;
  flex-direction: column;
  gap: 5px;
  min-width: 0;
  border: 0;
  margin: 0;
  padding: 0;
}

label,
legend {
  font-size: 13px;
  font-weight: 500;
  padding: 0;
}

input[type='number'],
input[type='date'],
select {
  font: inherit;
  font-size: 13px;
  padding: 7px 10px;
  border: 1px solid var(--border);
  border-radius: 8px;
  background: var(--surface-1);
  color: var(--text-primary);
  width: 100%;
}

input:focus-visible,
select:focus-visible {
  outline: 2px solid var(--series-1);
  outline-offset: 1px;
}

.hint {
  margin: 0;
  font-size: 12px;
  color: var(--text-secondary);
}

.flag {
  font-size: 11px;
  font-weight: 500;
  color: var(--critical);
  margin-left: 4px;
}

.flag.optional {
  color: var(--text-muted);
}

.goals {
  gap: 10px;
}

.goal-options {
  display: grid;
  gap: 8px;
}

@media (min-width: 900px) {
  .goal-options {
    grid-template-columns: repeat(3, minmax(0, 1fr));
  }
}

.goal {
  display: flex;
  gap: 9px;
  align-items: flex-start;
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 10px 12px;
  cursor: pointer;
  font-weight: 400;
}

.goal:has(input:checked) {
  border-color: var(--series-1);
  background: color-mix(in srgb, var(--series-1) 6%, var(--surface-1));
}

.goal:has(input:focus-visible) {
  outline: 2px solid var(--series-1);
  outline-offset: 1px;
}

.goal input {
  margin-top: 3px;
  flex: none;
  accent-color: var(--series-1);
}

.goal span {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.goal-sub {
  font-size: 12px;
}

.effects {
  margin: 2px 0 0;
  padding-left: 18px;
  font-size: 12px;
  color: var(--text-secondary);
}

.effects li + li {
  margin-top: 3px;
}

.actions {
  display: flex;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
}

.save {
  padding: 8px 16px;
  font-size: 13px;
}

.ok {
  font-size: 12px;
  color: var(--success-text);
}

.bad {
  font-size: 12px;
  color: var(--critical);
}

code {
  font-size: 11px;
  background: var(--page);
  padding: 2px 5px;
  border-radius: 4px;
}
</style>
