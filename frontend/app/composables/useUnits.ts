/**
 * Weight display in the lifter's configured unit.
 *
 * The backend stores and reports every load in kilograms - `units` in the
 * backend settings only ever changes presentation. Conversion therefore happens
 * here, at the display boundary, and never to a value on its way into a
 * calculation: ratios, percentages and level scores are unit-free, and
 * converting them would be wrong twice over.
 *
 * Dumb chart components take values already in display units plus a `unit`
 * label. Components that know their inputs are kilograms - StandardsRow - call
 * this themselves.
 */
import { computed } from 'vue'
import type { Profile } from '~/types/api'

const LB_PER_KG = 2.2046226218

export function useUnits() {
  // One shared key, so every component on the page reads a single request.
  const { data: profile } = useFetch<Profile>('/api/profile', { key: 'profile' })

  const unit = computed(() => profile.value?.units ?? 'kg')
  const factor = computed(() => (unit.value === 'lb' ? LB_PER_KG : 1))

  /** A kilogram value in display units, unrounded - for charts and axes. */
  function convert(value: number): number
  function convert(value: null | undefined): null
  function convert(value: number | null | undefined): number | null {
    return value === null || value === undefined ? null : value * factor.value
  }

  /** Converted and rounded, without a unit suffix - for a table with a unit header. */
  function amount(value: number | null | undefined, digits = 1): string {
    if (value === null || value === undefined) return '-'
    return (value * factor.value).toLocaleString(undefined, {
      minimumFractionDigits: 0,
      maximumFractionDigits: digits,
    })
  }

  /** Converted, rounded and suffixed: "82.5 kg" / "181.9 lb". */
  function weight(value: number | null | undefined, digits = 1): string {
    if (value === null || value === undefined) return '-'
    return `${amount(value, digits)} ${unit.value}`
  }

  return { unit, convert, amount, weight }
}
