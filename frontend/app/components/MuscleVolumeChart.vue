<script setup lang="ts">
/**
 * Working sets per week by muscle group, with the guidance threshold drawn as
 * a reference line.
 *
 * One series, so one colour for every bar - darkness is not used to restate bar
 * length. Bars that fall short of the threshold are drawn in the warning status
 * colour, which is a genuine state, not an identity, and is paired with a
 * labelled reference line so the colour never carries the meaning alone.
 */
import { computed, ref } from 'vue'
import { useChartSize } from '~/composables/useChartSize'
import { titleCase } from '~/utils/format'

const props = withDefaults(
  defineProps<{
    groups: { muscle_group: string; sets_per_week: number; volume_kg: number }[]
    threshold?: number
    maxRows?: number
  }>(),
  { threshold: 8, maxRows: 12 },
)

const wrap = ref<HTMLElement | null>(null)
const { width } = useChartSize(wrap, 520)

const ROW_H = 26
const BAR_H = 14
const LABEL_W = 96
const PAD_R = 44

const rows = computed(() => props.groups.slice(0, props.maxRows))
const height = computed(() => rows.value.length * ROW_H + 26)
const trackW = computed(() => Math.max(80, width.value - LABEL_W - PAD_R))

const scaled = computed(() => {
  if (rows.value.length === 0) return null
  const max = Math.max(...rows.value.map((g) => g.sets_per_week), props.threshold * 1.2)
  return {
    max,
    thresholdX: LABEL_W + (props.threshold / max) * trackW.value,
    items: rows.value.map((group, i) => ({
      ...group,
      i,
      y: i * ROW_H + 4,
      w: Math.max(2, (group.sets_per_week / max) * trackW.value),
      below: group.sets_per_week < props.threshold,
    })),
  }
})

/** Rounded data-end, square at the baseline (here the left edge). */
function barPath(x: number, y: number, w: number, h: number): string {
  const r = Math.min(4, w, h / 2)
  return `M${x},${y} L${x + w - r},${y} Q${x + w},${y} ${x + w},${y + r} L${x + w},${y + h - r} Q${x + w},${y + h} ${x + w - r},${y + h} L${x},${y + h} Z`
}
</script>

<template>
  <div ref="wrap" class="chart-wrap">
    <svg
      v-if="scaled"
      :width="width"
      :height="height"
      :viewBox="`0 0 ${width} ${height}`"
      role="img"
      aria-label="Working sets per week by muscle group"
    >
      <g v-for="item in scaled.items" :key="item.muscle_group">
        <text :x="LABEL_W - 10" :y="item.y + BAR_H - 2" text-anchor="end" class="row-label">
          {{ titleCase(item.muscle_group) }}
        </text>
        <path
          :d="barPath(LABEL_W, item.y, item.w, BAR_H)"
          :fill="item.below ? 'var(--warning)' : 'var(--series-1)'"
        />
        <text :x="LABEL_W + item.w + 8" :y="item.y + BAR_H - 2" class="value-label">
          {{ item.sets_per_week.toFixed(1) }}
        </text>
      </g>

      <!-- reference line: the threshold the colour change refers to -->
      <line
        :x1="scaled.thresholdX"
        :x2="scaled.thresholdX"
        y1="0"
        :y2="rows.length * ROW_H"
        stroke="var(--text-muted)"
        stroke-width="1"
      />
      <text :x="scaled.thresholdX" :y="height - 8" text-anchor="middle" class="axis">
        {{ threshold }} sets/week
      </text>
    </svg>
  </div>
</template>

<style scoped>
.chart-wrap {
  width: 100%;
}

svg {
  display: block;
  overflow: visible;
}

.row-label {
  fill: var(--text-secondary);
  font-size: 11px;
}

.value-label {
  fill: var(--text-primary);
  font-size: 11px;
  font-weight: 500;
  font-variant-numeric: tabular-nums;
}

.axis {
  fill: var(--text-muted);
  font-size: 10px;
}
</style>
