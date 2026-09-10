<script setup lang="ts">
/**
 * Card chrome shared by every chart: title, subtitle, and the table-view twin.
 *
 * Every chart ships a table view so no value is reachable only by hovering.
 */
import { ref } from 'vue'

defineProps<{
  /** Plain text title. Omit and use the `title` slot to attach provenance. */
  title?: string
  subtitle?: string
  /** Set when there is nothing to plot, so the card explains itself. */
  empty?: boolean
  emptyMessage?: string
}>()

const showTable = ref(false)
</script>

<template>
  <section class="card">
    <div class="card-head">
      <h2 class="card-title"><slot name="title">{{ title }}</slot></h2>
      <button
        v-if="!empty && $slots.table"
        class="link-quiet"
        type="button"
        :aria-pressed="showTable"
        @click="showTable = !showTable"
      >
        {{ showTable ? 'Chart' : 'Table' }}
      </button>
    </div>
    <p v-if="subtitle || $slots.subtitle" class="card-sub">
      <slot name="subtitle">{{ subtitle }}</slot>
    </p>

    <p v-if="empty" class="empty">{{ emptyMessage || 'No data yet.' }}</p>
    <div v-else-if="showTable" class="scroll-x">
      <slot name="table" />
    </div>
    <slot v-else />
  </section>
</template>
