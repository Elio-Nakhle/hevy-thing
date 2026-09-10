<script setup lang="ts">
/**
 * The dashboard's lead: are you getting stronger, and what changes next session.
 *
 * Everything else on the dashboard is the working. This is the answer, and it
 * is framed against the lifter's own past self rather than a percentile - the
 * percentile is what the strength page is for, and it lands badly in exactly
 * the case where encouragement matters most.
 */
import { computed } from 'vue'
import type { Headline } from '~/types/api'

const props = defineProps<{ headline: Headline | null | undefined }>()

const VERDICTS: Record<string, { colour: string; label: string }> = {
  progressing: { colour: 'var(--good)', label: 'Progressing' },
  holding: { colour: 'var(--series-1)', label: 'Holding' },
  slipping: { colour: 'var(--serious)', label: 'Slipping' },
  insufficient_data: { colour: 'var(--text-muted)', label: 'Not enough yet' },
}

const verdict = computed(() => VERDICTS[props.headline?.verdict ?? 'insufficient_data']!)

/** How the answer was reached, so the sentence is not a black box. */
const basis = computed(() => {
  const data = props.headline
  if (!data || data.lifts_tracked === 0) return ''
  const weeks = Math.round(data.window_days / 7)
  const lifts = data.lifts_tracked === 1 ? '1 lift' : `${data.lifts_tracked} lifts`
  return `From a trend line through ${lifts} with enough sessions in the last ${weeks} weeks.`
})
</script>

<template>
  <section v-if="headline" class="card lead" :style="{ '--accent': verdict.colour }">
    <div class="row">
      <span class="eyebrow secondary">Are you getting stronger?</span>
      <span class="badge" :style="{ background: verdict.colour }">{{ verdict.label }}</span>
    </div>

    <p class="answer">{{ headline.answer }}</p>

    <p v-if="basis" class="basis muted">
      {{ basis }} See <NuxtLink to="/strength">Strength standards</NuxtLink> for how that
      compares with other lifters.
    </p>

    <div v-if="headline.next_up" class="next">
      <p class="next-line">{{ headline.next_up.summary }}</p>
      <NuxtLink to="/next" class="btn next-btn">
        Take it to the rack
      </NuxtLink>
    </div>
  </section>
</template>

<style scoped>
.lead {
  border-left: 3px solid var(--accent);
}

.row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.eyebrow {
  font-size: 12px;
  font-weight: 500;
  text-transform: uppercase;
  letter-spacing: 0.06em;
}

.badge {
  color: #fff;
  font-size: 11px;
  font-weight: 500;
  padding: 2px 8px;
  border-radius: 999px;
  white-space: nowrap;
}

.answer {
  margin: 10px 0 0;
  font-size: 21px;
  font-weight: 600;
  line-height: 1.3;
  letter-spacing: -0.01em;
  max-width: 60ch;
}

.basis {
  margin: 8px 0 0;
  font-size: 12px;
  max-width: 70ch;
}

.next {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  flex-wrap: wrap;
  margin-top: 16px;
  padding-top: 14px;
  border-top: 1px solid var(--gridline);
}

.next-line {
  margin: 0;
  font-size: 13px;
  color: var(--text-secondary);
  flex: 1;
  min-width: 220px;
}

.next-btn {
  text-decoration: none;
  flex: none;
}
</style>
