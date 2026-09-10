<script setup lang="ts">
/**
 * Stat tile: label, value, optional delta and sparkline.
 *
 * Proportional figures on the value - `tabular-nums` would make a number like
 * 121 look loose at this size.
 */
import { computed } from 'vue'

const props = withDefaults(
  defineProps<{
    /** Plain text label. Omit and use the `label` slot to attach provenance. */
    label?: string
    value: string
    unit?: string
    /** Signed percentage change against a named period. */
    delta?: number | null
    deltaLabel?: string
    /** Higher is better? Drives the delta colour. */
    upIsGood?: boolean
    spark?: number[]
  }>(),
  { upIsGood: true, spark: () => [] },
)

const deltaColor = computed(() => {
  if (props.delta === null || props.delta === undefined || Math.abs(props.delta) < 0.05) {
    return 'var(--text-secondary)'
  }
  const good = props.delta > 0 === props.upIsGood
  return good ? 'var(--success-text)' : 'var(--critical)'
})

const W = 96
const H = 26

const sparkPath = computed(() => {
  const points = props.spark
  if (points.length < 2) return ''
  const min = Math.min(...points)
  const max = Math.max(...points)
  const span = max - min || 1
  return points
    .map((value, i) => {
      const x = (i / (points.length - 1)) * (W - 2) + 1
      const y = H - 2 - ((value - min) / span) * (H - 4)
      return `${i === 0 ? 'M' : 'L'}${x.toFixed(1)},${y.toFixed(1)}`
    })
    .join(' ')
})

const sparkEnd = computed(() => {
  const points = props.spark
  if (points.length < 2) return null
  const min = Math.min(...points)
  const max = Math.max(...points)
  const span = max - min || 1
  const last = points[points.length - 1]!
  return { x: W - 1, y: H - 2 - ((last - min) / span) * (H - 4) }
})
</script>

<template>
  <Card class="gap-1.5 px-[18px] pt-4 pb-4">
    <span class="text-muted-foreground text-xs"><slot name="label">{{ label }}</slot></span>
    <div class="flex items-end justify-between gap-2.5">
      <span class="text-[26px] leading-[1.1] font-semibold tracking-[-0.02em]">
        {{ value }}<span v-if="unit" class="text-muted-foreground ml-[3px] text-[13px] font-medium">{{ unit }}</span>
      </span>
      <svg
        v-if="sparkPath"
        class="shrink-0"
        :width="W"
        :height="H"
        :viewBox="`0 0 ${W} ${H}`"
        aria-hidden="true"
      >
        <path :d="sparkPath" fill="none" stroke="var(--baseline)" stroke-width="2"
              stroke-linecap="round" stroke-linejoin="round" />
        <circle v-if="sparkEnd" :cx="sparkEnd.x" :cy="sparkEnd.y" r="2.5" fill="var(--series-1)" />
      </svg>
    </div>
    <span v-if="delta !== null && delta !== undefined" class="text-xs" :style="{ color: deltaColor }">
      {{ delta > 0 ? '+' : '' }}{{ delta.toFixed(1) }}%
      <span class="text-subtle">{{ deltaLabel }}</span>
    </span>
  </Card>
</template>
