<script setup lang="ts">
/**
 * Weekly volume columns.
 *
 * Columns cap at 24px wide with a 2px surface gap between neighbours, rounded
 * at the data end and square at the baseline. Hit targets span the full band so
 * a thin column is still easy to hover.
 */
import { computed, ref } from 'vue'
import { useChartSize } from '~/composables/useChartSize'
import { compact, niceTicks, shortDate } from '~/utils/format'

const props = withDefaults(
  defineProps<{
    bars: { label: string; value: number; sub?: string }[]
    height?: number
    unit?: string
  }>(),
  { height: 220, unit: 'kg' },
)

const wrap = ref<HTMLElement | null>(null)
const { width } = useChartSize(wrap)

const PAD = { top: 16, right: 12, bottom: 26, left: 46 }
const MAX_BAR = 24
const GAP = 2

const plot = computed(() => ({
  w: Math.max(120, width.value - PAD.left - PAD.right),
  h: Math.max(80, props.height - PAD.top - PAD.bottom),
}))

const scaled = computed(() => {
  if (props.bars.length === 0) return null
  const max = Math.max(...props.bars.map((b) => b.value), 1)
  const ticks = niceTicks(0, max, 4)
  const top = Math.max(max, ticks[ticks.length - 1] ?? max)
  const band = plot.value.w / props.bars.length
  const barW = Math.min(MAX_BAR, Math.max(3, band - GAP))
  const base = PAD.top + plot.value.h

  const items = props.bars.map((bar, i) => {
    const h = (bar.value / top) * plot.value.h
    return {
      ...bar,
      i,
      bandX: PAD.left + i * band,
      band,
      x: PAD.left + i * band + (band - barW) / 2,
      w: barW,
      y: base - h,
      h: Math.max(h, bar.value > 0 ? 1.5 : 0),
    }
  })

  return {
    items,
    base,
    ticks: ticks.map((v) => ({ v, y: base - (v / top) * plot.value.h })),
  }
})

const xTicks = computed(() => {
  const s = scaled.value
  if (!s) return []
  const step = Math.max(1, Math.ceil(s.items.length / Math.max(2, Math.floor(plot.value.w / 80))))
  return s.items.filter((_, i) => i % step === 0 || i === s.items.length - 1)
})

const hover = ref<number | null>(null)
const active = computed(() => (hover.value === null ? null : scaled.value?.items[hover.value] ?? null))

/**
 * A rounded data-end with a square baseline: the top corners get the radius,
 * the bottom two stay sharp so every column sits flat on the axis.
 */
function barPath(x: number, y: number, w: number, h: number): string {
  const r = Math.min(4, w / 2, h)
  const bottom = y + h
  return `M${x},${bottom} L${x},${y + r} Q${x},${y} ${x + r},${y} L${x + w - r},${y} Q${x + w},${y} ${x + w},${y + r} L${x + w},${bottom} Z`
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
      :aria-label="`Column chart, ${bars.length} periods`"
      @mouseleave="hover = null"
    >
      <line
        v-for="tick in scaled.ticks"
        :key="`g${tick.v}`"
        :x1="PAD.left"
        :x2="PAD.left + plot.w"
        :y1="tick.y"
        :y2="tick.y"
        stroke="var(--gridline)"
        stroke-width="1"
      />
      <text
        v-for="tick in scaled.ticks"
        :key="`yl${tick.v}`"
        :x="PAD.left - 8"
        :y="tick.y + 4"
        text-anchor="end"
        class="axis"
      >
        {{ compact(tick.v) }}
      </text>

      <path
        v-for="item in scaled.items"
        :key="`b${item.i}`"
        :d="barPath(item.x, item.y, item.w, item.h)"
        :fill="hover === item.i ? 'var(--level-5)' : 'var(--series-1)'"
      />

      <!-- full-band hit targets, so thin columns stay easy to hover -->
      <rect
        v-for="item in scaled.items"
        :key="`h${item.i}`"
        :x="item.bandX"
        :y="PAD.top"
        :width="item.band"
        :height="plot.h"
        fill="transparent"
        @mouseenter="hover = item.i"
      />

      <line
        :x1="PAD.left"
        :x2="PAD.left + plot.w"
        :y1="scaled.base"
        :y2="scaled.base"
        stroke="var(--baseline)"
        stroke-width="1"
      />

      <text
        v-for="item in xTicks"
        :key="`xl${item.i}`"
        :x="item.bandX + item.band / 2"
        :y="height - 8"
        text-anchor="middle"
        class="axis"
      >
        {{ shortDate(item.label) }}
      </text>

      <g v-if="active" :transform="`translate(${Math.min(active.bandX, PAD.left + plot.w - 118)}, ${Math.max(2, active.y - 40)})`">
        <rect width="118" height="36" rx="6" fill="var(--overlay)" />
        <text x="8" y="14" class="tip-label">{{ shortDate(active.label) }}</text>
        <text x="8" y="28" class="tip-value">
          {{ Math.round(active.value).toLocaleString() }} {{ unit }}
        </text>
      </g>
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

.axis {
  fill: var(--text-muted);
  font-size: 11px;
  font-variant-numeric: tabular-nums;
}

.tip-label {
  fill: #fff;
  opacity: 0.75;
  font-size: 10px;
}

.tip-value {
  fill: #fff;
  font-size: 12px;
  font-weight: 600;
}
</style>
