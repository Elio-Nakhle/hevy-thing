<script setup lang="ts" generic="T extends string | number">
/**
 * The segmented control behind every range and mode picker.
 *
 * A thin wrapper over `ToggleGroup` for two reasons: the selected segment is
 * the primary blue rather than the neutral accent shadcn ships with, and this
 * refuses to deselect - a chart whose range has been unset has nothing to draw.
 */
const model = defineModel<T>({ required: true })

const props = defineProps<{
  options: { value: T; label: string }[]
  /** Names the group for a screen reader, e.g. "Time range". */
  label?: string
}>()

// `unknown`, because the group is typed for its multi-select form too and can
// emit an array or null; only a single string is a selection here.
function select(next: unknown) {
  if (typeof next !== 'string') return
  const match = props.options.find((option) => String(option.value) === next)
  if (match) model.value = match.value
}
</script>

<template>
  <ToggleGroup
    type="single"
    variant="outline"
    size="sm"
    :aria-label="label"
    :model-value="String(model)"
    @update:model-value="select"
  >
    <ToggleGroupItem
      v-for="option in options"
      :key="String(option.value)"
      :value="String(option.value)"
      class="data-[state=on]:bg-primary data-[state=on]:text-primary-foreground text-xs"
    >
      {{ option.label }}
    </ToggleGroupItem>
  </ToggleGroup>
</template>
