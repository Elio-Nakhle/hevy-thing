<script setup lang="ts">
/**
 * One lift plotted against its five strength-standard bands.
 *
 * The bands are an ordered scale, so they use the ordinal blue ramp (one hue,
 * light to dark) rather than five categorical identities - the darkness *is*
 * the meaning. A 2px surface gap separates the bands instead of a border.
 *
 * The x-axis is the level scale (0 = beginner ... 4 = elite), not kilograms:
 * that makes different lifts directly comparable in one column, which is the
 * whole point of standards. The load thresholds ride the axis underneath.
 *
 * Every weight prop arrives in kilograms, as the API reports them, and is
 * converted here for display.
 */
import { computed, ref } from 'vue'
import { useChartSize } from '~/composables/useChartSize'
import { LEVELS } from '~/utils/format'

const { unit: unitLabel, amount } = useUnits()

const props = withDefaults(
  defineProps<{
    title: string
    /** All weights are in kilograms; display conversion happens here. */
    e1rm: number
    levelScore: number
    level: string
    thresholds: Record<string, number>
    nextLevel?: string | null
    kgToNext?: number | null
    /** Draw the level names under the bands (once per group is enough). */
    showScale?: boolean
  }>(),
  { showScale: false },
)

const wrap = ref<HTMLElement | null>(null)
const { width } = useChartSize(wrap, 520)

const BAND_H = 14
const GAP = 2
const PAD_R = 8

const plotW = computed(() => Math.max(120, width.value - PAD_R))

// A score of `i` *is* the threshold for level `i`, so band `i` covers scores i..i+1
// and the five bands span 5 score units. The track adds 0.35 of a unit of lead-in
// on the left so a sub-beginner marker stays visible, giving a domain of
// -0.35..5 - and the marker and the bands must divide by that same span or the
// bands overflow the track.
const DOMAIN_MIN = -0.35
const DOMAIN_SPAN = 5 - DOMAIN_MIN

/** Level score 0..4 mapped across the track, clamped into view at both ends. */
const markerX = computed(() => {
  const clamped = Math.max(DOMAIN_MIN, Math.min(4.35, props.levelScore))
  return ((clamped - DOMAIN_MIN) / DOMAIN_SPAN) * plotW.value
})

const bands = computed(() => {
  const unit = plotW.value / DOMAIN_SPAN
  const start = -DOMAIN_MIN * unit
  return LEVELS.map((name, i) => ({
    name,
    x: start + i * unit + (i === 0 ? 0 : GAP / 2),
    w: unit - GAP,
    fill: `var(--level-${i + 1})`,
    kg: props.thresholds[name],
  }))
})

const hovered = ref<string | null>(null)
</script>

<template>
  <div ref="wrap" class="row">
    <div class="row-head">
      <span class="row-title">{{ title }}</span>
      <span class="row-value">
        {{ amount(e1rm) }} <span class="muted">{{ unitLabel }} e1RM</span>
      </span>
    </div>

    <svg
      :width="width"
      :height="showScale ? BAND_H + 34 : BAND_H + 16"
      :viewBox="`0 0 ${width} ${showScale ? BAND_H + 34 : BAND_H + 16}`"
      role="img"
      :aria-label="`${title}: ${e1rm.toFixed(1)} kilograms, ${level}, level score ${levelScore.toFixed(2)} of 4`"
      @mouseleave="hovered = null"
    >
      <g>
        <rect
          v-for="band in bands"
          :key="band.name"
          :x="band.x"
          y="8"
          :width="band.w"
          :height="BAND_H"
          :rx="2"
          :fill="band.fill"
          :fill-opacity="hovered === null || hovered === band.name ? 1 : 0.45"
          @mouseenter="hovered = band.name"
        />
      </g>

      <!-- the lifter's position: a marker with a surface ring so it stays
           legible wherever it lands on the ramp -->
      <g :transform="`translate(${markerX}, 0)`">
        <line
          x1="0"
          x2="0"
          :y1="4"
          :y2="8 + BAND_H + 4"
          stroke="var(--surface-1)"
          stroke-width="4"
          stroke-linecap="round"
        />
        <line
          x1="0"
          x2="0"
          :y1="4"
          :y2="8 + BAND_H + 4"
          stroke="var(--text-primary)"
          stroke-width="2"
          stroke-linecap="round"
        />
      </g>

      <template v-if="showScale">
        <text
          v-for="band in bands"
          :key="`t${band.name}`"
          :x="band.x + band.w / 2"
          :y="BAND_H + 30"
          text-anchor="middle"
          class="scale-label"
        >
          {{ band.name }}
        </text>
      </template>
    </svg>

    <p class="row-foot">
      <span class="level-chip">
        <span class="chip-dot" :style="{ background: `var(--level-${Math.max(1, Math.min(5, Math.floor(levelScore) + 1))})` }" />
        {{ level }}
      </span>
      <span class="secondary">score {{ levelScore.toFixed(2) }} / 4</span>
      <span v-if="hovered" class="secondary">
        {{ hovered }} starts at {{ amount(thresholds[hovered]) }} {{ unitLabel }}
      </span>
      <span v-else-if="nextLevel && kgToNext !== null && kgToNext !== undefined" class="secondary">
        +{{ amount(kgToNext) }} {{ unitLabel }} to {{ nextLevel }}
      </span>
    </p>

    <slot />
  </div>
</template>

<style scoped>
.row {
  padding: 12px 0;
  border-bottom: 1px solid var(--gridline);
}

.row:last-child {
  border-bottom: 0;
}

.row-head {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 2px;
}

.row-title {
  font-size: 13px;
  font-weight: 500;
}

.row-value {
  font-size: 13px;
  font-weight: 600;
  font-variant-numeric: tabular-nums;
}

svg {
  display: block;
  overflow: visible;
}

.scale-label {
  fill: var(--text-muted);
  font-size: 10px;
}

.row-foot {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 12px;
  margin: 6px 0 0;
  font-size: 12px;
}

.level-chip {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-weight: 500;
  text-transform: capitalize;
}

.chip-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  display: inline-block;
}
</style>
