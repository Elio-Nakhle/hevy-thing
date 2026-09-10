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

const names = (lifts: string[]) => lifts.join(', ')
</script>

<template>
  <Card
    v-if="headline"
    class="border-l-[3px]"
    :style="{ borderLeftColor: verdict.colour }"
  >
    <CardContent class="flex flex-col">
      <div class="flex items-center justify-between gap-3">
        <span class="text-muted-foreground text-xs font-medium tracking-[0.06em] uppercase">
          Are you getting stronger?
        </span>
        <span
          class="rounded-full px-2 py-0.5 text-[11px] font-medium whitespace-nowrap text-white"
          :style="{ background: verdict.colour }"
        >{{ verdict.label }}</span>
      </div>

      <p class="mt-2.5 mb-0 max-w-[60ch] text-[21px] leading-[1.3] font-semibold tracking-[-0.01em]">
        <template v-if="headline.verdict === 'insufficient_data'">
          {{ headline.answer }}
        </template>
        <template v-else-if="headline.verdict === 'progressing'">
          Yes. Your typical lift is up {{ headline.median_change_pct_per_month?.toFixed(1) }}% a month -
        </template>
        <template v-else-if="headline.verdict === 'slipping'">
          Not right now. Your typical lift is down {{ Math.abs(headline.median_change_pct_per_month ?? 0).toFixed(1) }}% a month -
        </template>
        <template v-else-if="headline.verdict === 'holding'">
          Holding. Your typical lift moves {{ (headline.median_change_pct_per_month ?? 0) >= 0 ? '+' : '' }}{{ headline.median_change_pct_per_month?.toFixed(1) }}% a month -
        </template>
        <template v-if="headline.lifts_up">
          <span class="cursor-help border-b border-dotted border-current" :title="names(headline.lifts_up_names)">
            {{ headline.lifts_up }} of {{ headline.lifts_tracked }} climbing</span><template v-if="headline.lifts_down">, </template>
        </template>
        <template v-if="headline.lifts_down">
          <span class="cursor-help border-b border-dotted border-current" :title="names(headline.lifts_down_names)">
            {{ headline.lifts_down }} sliding</span>
        </template>
        <template v-if="!headline.lifts_up && !headline.lifts_down">
          <span class="cursor-help border-b border-dotted border-current" :title="names(headline.lifts_flat_names)">
            none of {{ headline.lifts_tracked }} clearly either way</span>
        </template>
      </p>

      <p v-if="basis" class="text-subtle mt-2 mb-0 max-w-[70ch] text-xs">
        {{ basis }} See <NuxtLink to="/strength">Strength standards</NuxtLink> for how that
        compares with other lifters.
      </p>

      <div
        v-if="headline.next_up"
        class="border-gridline mt-4 flex flex-wrap items-center justify-between gap-4 border-t pt-3.5"
      >
        <p class="text-muted-foreground m-0 min-w-[220px] flex-1 text-[13px]">
          {{ headline.next_up.summary }}
        </p>
        <Button as-child variant="outline" size="sm" class="shrink-0">
          <NuxtLink to="/next" class="no-underline">Take it to the rack</NuxtLink>
        </Button>
      </div>
    </CardContent>
  </Card>
</template>
