<script setup lang="ts">
/**
 * A derived number's name, with where it came from attached.
 *
 * `<abbr title>` rather than a custom tooltip: it is the element that means
 * "term with an expansion", it gets a hover tooltip and a dotted underline from
 * the browser, and it needs no JavaScript. Native tooltips do not open on
 * touch, so anywhere that matters on a phone states its provenance inline
 * instead of relying on this.
 */
import { computed } from 'vue'

const props = defineProps<{
  /** A key from the glossary, e.g. "e1rm". */
  id: string
  /** Sentence-case it, for a table header or the start of a sentence. Ignored
   *  for a term that already carries capitals of its own. */
  capitalize?: boolean
}>()

const { label, provenance } = useGlossary()

const text = computed(() => {
  const value = label(props.id)
  // Only sentence-case a label that is entirely lower case. "e1RM" and "DOTS"
  // carry their own casing, and "E1RM" is simply wrong.
  if (props.capitalize && value === value.toLowerCase()) {
    return value.charAt(0).toUpperCase() + value.slice(1)
  }
  return value
})
</script>

<template>
  <abbr class="term" :title="provenance(props.id)">{{ text }}</abbr>
</template>

<style scoped>
.term {
  text-decoration: underline dotted;
  text-underline-offset: 3px;
  text-decoration-color: var(--baseline);
  cursor: help;
}
</style>
