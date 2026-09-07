import { onBeforeUnmount, onMounted, ref, type Ref } from 'vue'

/**
 * Track an element's width so charts can render at real pixel dimensions.
 *
 * Charts are drawn at true size rather than scaled with `preserveAspectRatio`,
 * which would stretch the text along with the geometry.
 */
export function useChartSize(el: Ref<HTMLElement | null>, fallback = 640) {
  const width = ref(fallback)
  let observer: ResizeObserver | null = null

  onMounted(() => {
    if (!el.value) return
    observer = new ResizeObserver((entries) => {
      const next = entries[0]?.contentRect.width
      if (next && next > 0) width.value = Math.round(next)
    })
    observer.observe(el.value)
    width.value = Math.round(el.value.clientWidth) || fallback
  })

  onBeforeUnmount(() => observer?.disconnect())

  return { width }
}
