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
  <Card>
    <CardHeader>
      <CardTitle><slot name="title">{{ title }}</slot></CardTitle>
      <CardAction v-if="!empty && $slots.table">
        <Button
          variant="link"
          size="sm"
          class="text-muted-foreground h-auto p-0 text-xs underline underline-offset-[3px]"
          :aria-pressed="showTable"
          @click="showTable = !showTable"
        >
          {{ showTable ? 'Chart' : 'Table' }}
        </Button>
      </CardAction>
      <CardDescription v-if="subtitle || $slots.subtitle">
        <slot name="subtitle">{{ subtitle }}</slot>
      </CardDescription>
    </CardHeader>

    <CardContent>
      <p v-if="empty" class="text-muted-foreground py-7 text-center text-[13px]">
        {{ emptyMessage || 'No data yet.' }}
      </p>
      <div v-else-if="showTable" class="overflow-x-auto">
        <slot name="table" />
      </div>
      <slot v-else />
    </CardContent>
  </Card>
</template>
