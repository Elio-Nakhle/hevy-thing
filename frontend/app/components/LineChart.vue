<script setup lang="ts">
/**
 * Time-series line chart with an optional least-squares trend line and a
 * crosshair tooltip.
 *
 * Single series, so no legend box - the card title names what is plotted. The
 * endpoint and the maximum are direct-labelled; every other value is on the
 * axis, the tooltip and the table view.
 */
import { computed, ref } from 'vue'
import { useChartSize } from '~/composables/useChartSize'
import { niceTicks, shortDate } from '~/utils/format'

const props = withDefaults(
  defineProps<{
    points: { date: string; value: number }[]
    height?: number
    unit?: string
    showTrend?: boolean
  }>(),
  { height: 240, unit: 'kg', showTrend: true },
)

const wrap = ref<HTMLElement | null>(null)
const { width } = useChartSize(wrap)

const PAD = { top: 18, right: 52, bottom: 26, left: 44 }

const plot = computed(() => ({
  w: Math.max(120, width.value - PAD.left - PAD.right),
  h: Math.max(80, props.height - PAD.top - PAD.bottom),
}))

const scaled = computed(() => {
  const points = props.points
  if (points.length === 0) return null

  const times = points.map((p) => new Date(p.date).getTime())
  const values = points.map((p) => p.value)
  const tMin = Math.min(...times)
  const tMax = Math.max(...times)
  const tSpan = tMax - tMin || 1

  // Pad the value range so the line never touches the frame.
  const vMin = Math.min(...values)
  const vMax = Math.max(...values)
  const headroom = (vMax - vMin || Math.max(vMax * 0.1, 1)) * 0.15
  const lo = Math.max(0, vMin - headroom)
  const hi = vMax + headroom

  const x = (t: number) => PAD.left + ((t - tMin) / tSpan) * plot.value.w
  const y = (v: number) => PAD.top + plot.value.h - ((v - lo) / (hi - lo || 1)) * plot.value.h

  const nodes = points.map((p, i) => ({
    ...p,
    i,
    cx: x(times[i]!),
    cy: y(p.value),
  }))

  return { nodes, x, y, tMin, tMax, lo, hi, times, values }
})

const linePath = computed(() => {
  const s = scaled.value
  if (!s) return ''
  return s.nodes.map((n, i) => `${i === 0 ? 'M' : 'L'}${n.cx.toFixed(1)},${n.cy.toFixed(1)}`).join(' ')
})

const areaPath = computed(() => {
  const s = scaled.value
  if (!s || s.nodes.length < 2) return ''
  const base = PAD.top + plot.value.h
  const first = s.nodes[0]!
  const last = s.nodes[s.nodes.length - 1]!
  return `${linePath.value} L${last.cx.toFixed(1)},${base} L${first.cx.toFixed(1)},${base} Z`
})

/** Least-squares fit over the same points, drawn as a thin reference. */
const trend = computed(() => {
  const s = scaled.value
  if (!s || !props.showTrend || s.nodes.length < 4) return null
  const n = s.nodes.length
  const meanT = s.times.reduce((a, b) => a + b, 0) / n
  const meanV = s.values.reduce((a, b) => a + b, 0) / n
  let cov = 0
  let variance = 0
  for (let i = 0; i < n; i++) {
    cov += (s.times[i]! - meanT) * (s.values[i]! - meanV)
    variance += (s.times[i]! - meanT) ** 2
  }
  if (variance === 0) return null
  const slope = cov / variance
  const at = (t: number) => meanV + slope * (t - meanT)
  return {
    x1: s.x(s.tMin),
    y1: s.y(at(s.tMin)),
    x2: s.x(s.tMax),
    y2: s.y(at(s.tMax)),
    // kg per 30 days
    perMonth: slope * 1000 * 60 * 60 * 24 * 30,
  }
})

const yTicks = computed(() => {
  const s = scaled.value
  if (!s) return []
  return niceTicks(s.lo, s.hi, 4).map((v) => ({ v, y: s.y(v) }))
})

const xTicks = computed(() => {
  const s = scaled.value
  if (!s || s.nodes.length === 0) return []
  const step = Math.max(1, Math.ceil(s.nodes.length / Math.max(2, Math.floor(plot.value.w / 90))))
  return s.nodes.filter((_, i) => i % step === 0 || i === s.nodes.length - 1)
})

/** Endpoint and peak get a direct label; nothing else does. */
const labelled = computed(() => {
  const s = scaled.value
  if (!s || s.nodes.length === 0) return []
  const last = s.nodes[s.nodes.length - 1]!
  const peak = s.nodes.reduce((a, b) => (b.value > a.value ? b : a))
  return peak.i === last.i || Math.abs(peak.cx - last.cx) < 46 ? [last] : [peak, last]
})

const hover = ref<number | null>(null)

function onMove(event: MouseEvent) {
  const s = scaled.value
  if (!s) return
  const rect = (event.currentTarget as SVGElement).getBoundingClientRect()
  const x = event.clientX - rect.left
  let nearest = 0
  let best = Infinity
  s.nodes.forEach((n, i) => {
    const d = Math.abs(n.cx - x)
    if (d < best) {
      best = d
      nearest = i
    }
  })
  hover.value = nearest
}

const active = computed(() => (hover.value === null ? null : scaled.value?.nodes[hover.value] ?? null))

const tooltipX = computed(() => {
  const node = active.value
  if (!node) return 0
  // Flip the tooltip to the left of the crosshair near the right edge.
  return node.cx > PAD.left + plot.value.w - 110 ? node.cx - 116 : node.cx + 10
})
</script>

<template>
  <div ref="wrap" class="w-full">
    <svg
      v-if="scaled"
      :width="width"
      :height="height"
      :viewBox="`0 0 ${width} ${height}`"
      role="img"
      :aria-label="`Line chart, ${points.length} sessions`"
      class="block overflow-visible"
      @mousemove="onMove"
      @mouseleave="hover = null"
    >
      <!-- gridlines: solid hairlines, one shade off the surface -->
      <g>
        <line
          v-for="tick in yTicks"
          :key="`g${tick.v}`"
          :x1="PAD.left"
          :x2="PAD.left + plot.w"
          :y1="tick.y"
          :y2="tick.y"
          stroke="var(--gridline)"
          stroke-width="1"
        />
      </g>

      <text
        v-for="tick in yTicks"
        :key="`yl${tick.v}`"
        :x="PAD.left - 8"
        :y="tick.y + 4"
        text-anchor="end"
        class="fill-subtle text-[11px] tabular-nums"
      >
        {{ Math.round(tick.v).toLocaleString() }}
      </text>

      <text
        v-for="node in xTicks"
        :key="`xl${node.i}`"
        :x="node.cx"
        :y="height - 8"
        text-anchor="middle"
        class="fill-subtle text-[11px] tabular-nums"
      >
        {{ shortDate(node.date) }}
      </text>

      <path :d="areaPath" fill="var(--series-1)" fill-opacity="0.1" />

      <line
        v-if="trend"
        :x1="trend.x1"
        :y1="trend.y1"
        :x2="trend.x2"
        :y2="trend.y2"
        stroke="var(--text-muted)"
        stroke-width="1.5"
        stroke-linecap="round"
      />

      <path
        :d="linePath"
        fill="none"
        stroke="var(--series-1)"
        stroke-width="2"
        stroke-linejoin="round"
        stroke-linecap="round"
      />

      <!-- direct labels: endpoint and peak only -->
      <g v-for="node in labelled" :key="`lab${node.i}`">
        <circle
          :cx="node.cx"
          :cy="node.cy"
          r="4"
          fill="var(--series-1)"
          stroke="var(--surface-1)"
          stroke-width="2"
        />
        <text
          :x="node.cx + (node.cx > PAD.left + plot.w - 40 ? -8 : 8)"
          :y="node.cy - 8"
          :text-anchor="node.cx > PAD.left + plot.w - 40 ? 'end' : 'start'"
          class="fill-foreground text-[11px] font-semibold"
        >
          {{ Math.round(node.value) }}
        </text>
      </g>

      <!-- crosshair -->
      <g v-if="active">
        <line
          :x1="active.cx"
          :x2="active.cx"
          :y1="PAD.top"
          :y2="PAD.top + plot.h"
          stroke="var(--baseline)"
          stroke-width="1"
        />
        <circle
          :cx="active.cx"
          :cy="active.cy"
          r="4.5"
          fill="var(--series-1)"
          stroke="var(--surface-1)"
          stroke-width="2"
        />
        <g :transform="`translate(${tooltipX}, ${Math.max(PAD.top, active.cy - 34)})`">
          <rect width="106" height="34" rx="6" fill="var(--overlay)" />
          <text x="8" y="14" class="fill-white text-[10px] opacity-75">{{ shortDate(active.date) }}</text>
          <text x="8" y="27" class="fill-white text-xs font-semibold">{{ active.value.toFixed(1) }} {{ unit }}</text>
        </g>
      </g>
    </svg>

    <p v-if="trend" class="text-muted-foreground mt-2 mb-0 text-xs">
      Trend
      <strong :style="{ color: trend.perMonth >= 0 ? 'var(--success-text)' : 'var(--critical)' }">
        {{ trend.perMonth >= 0 ? '+' : '' }}{{ trend.perMonth.toFixed(1) }} {{ unit }}/month
      </strong>
    </p>
  </div>
</template>
