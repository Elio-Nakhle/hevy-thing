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
    label: string
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
  <div class="card tile">
    <span class="tile-label">{{ label }}</span>
    <div class="tile-value-row">
      <span class="tile-value">{{ value }}<span v-if="unit" class="tile-unit">{{ unit }}</span></span>
      <svg
        v-if="sparkPath"
        class="tile-spark"
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
    <span v-if="delta !== null && delta !== undefined" class="tile-delta" :style="{ color: deltaColor }">
      {{ delta > 0 ? '+' : '' }}{{ delta.toFixed(1) }}%
      <span class="muted">{{ deltaLabel }}</span>
    </span>
  </div>
</template>

<style scoped>
.tile {
  display: flex;
  flex-direction: column;
  gap: 6px;
  padding: 16px 18px;
}

.tile-label {
  color: var(--text-secondary);
  font-size: 12px;
}

.tile-value-row {
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  gap: 10px;
}

.tile-value {
  font-size: 26px;
  font-weight: 600;
  line-height: 1.1;
  letter-spacing: -0.02em;
}

.tile-unit {
  font-size: 13px;
  font-weight: 500;
  color: var(--text-secondary);
  margin-left: 3px;
}

.tile-spark {
  flex: none;
}

.tile-delta {
  font-size: 12px;
}
</style>
