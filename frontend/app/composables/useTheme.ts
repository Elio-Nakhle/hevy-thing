/**
 * Light / dark / follow-the-system, as a three-way cycle.
 *
 * The choice is written to `data-theme` on the root element and to
 * localStorage. "System" removes the attribute rather than resolving it here,
 * so the CSS keeps deciding from `prefers-color-scheme` and the page follows
 * the OS switching mid-session.
 *
 * Lives in a composable because the toggle moved into the sidebar footer while
 * the restore-on-mount belongs to the app shell, and the two must agree.
 */
import { useState } from '#app'

const STORAGE_KEY = 'hevy-coach-theme'

export type Theme = 'light' | 'dark' | 'system'

export function useTheme() {
  const theme = useState<Theme>('theme', () => 'system')

  function apply(next: Theme) {
    theme.value = next
    if (!import.meta.client) return
    const root = document.documentElement
    try {
      if (next === 'system') {
        root.removeAttribute('data-theme')
        localStorage.removeItem(STORAGE_KEY)
      } else {
        root.setAttribute('data-theme', next)
        localStorage.setItem(STORAGE_KEY, next)
      }
    } catch {
      // Private browsing can refuse writes. The theme still applies this visit.
    }
  }

  function cycleTheme() {
    apply(theme.value === 'light' ? 'dark' : theme.value === 'dark' ? 'system' : 'light')
  }

  /** Adopt the stored choice. Called once, from the app shell on mount - the
   *  server has no localStorage, and deciding during render would make the two
   *  disagree. */
  function restoreTheme() {
    if (!import.meta.client) return
    try {
      const stored = localStorage.getItem(STORAGE_KEY)
      if (stored === 'light' || stored === 'dark') apply(stored)
    } catch {
      // No stored preference available; the system default stands.
    }
  }

  return { theme, apply, cycleTheme, restoreTheme }
}
