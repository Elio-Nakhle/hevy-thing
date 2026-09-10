/**
 * Plain-language mode, and where each number comes from.
 *
 * Both read from one table - `/api/glossary`, built in
 * `backend/src/hevy_coach/provenance.py` - so a term's tooltip cannot end up
 * describing something other than what its label says. The backend owns the
 * wording because the reasoning it paraphrases lives in the analytics modules'
 * own docstrings, and a second copy over here would drift from them.
 *
 * The mode is per-browser rather than part of the lifter profile: it is a
 * reading preference, not a fact about the athlete, and the two people looking
 * at one local install may not want the same one.
 */
import type { Glossary } from '~/types/api'

const STORAGE_KEY = 'hevy-coach-plain-language'

export function useGlossary() {
  // One shared key, so every <Term> on the page reads a single request.
  const { data: glossary } = useFetch<Glossary>('/api/glossary', { key: 'glossary' })
  const plain = useState<boolean>('plain-language', () => false)

  /** What to call a term right now. Unknown ids show as themselves, which is
   *  ugly enough to notice in development and harmless in production. */
  function label(id: string): string {
    const entry = glossary.value?.[id]
    if (!entry) return id
    return plain.value ? entry.plain : entry.term
  }

  /** Where the number comes from, as one sentence. Empty for an unknown id. */
  function detail(id: string): string {
    return glossary.value?.[id]?.detail ?? ''
  }

  function source(id: string): string | null {
    return glossary.value?.[id]?.source ?? null
  }

  /** Provenance plus attribution, as one string for a tooltip. */
  function provenance(id: string): string {
    const text = detail(id)
    const from = source(id)
    return from ? `${text} Source: ${from}.` : text
  }

  function setPlain(next: boolean) {
    plain.value = next
    if (!import.meta.client) return
    try {
      localStorage.setItem(STORAGE_KEY, next ? '1' : '0')
    } catch {
      // Private browsing can refuse writes. The mode still applies this visit.
    }
  }

  /** Adopt the stored preference. Called once, from the app shell on mount -
   *  reading it during setup would render one thing on the server and another
   *  in the browser. */
  function restorePlain() {
    if (!import.meta.client) return
    try {
      if (localStorage.getItem(STORAGE_KEY) === '1') plain.value = true
    } catch {
      // No stored preference available; the default stands.
    }
  }

  return {
    glossary,
    plain,
    label,
    detail,
    source,
    provenance,
    setPlain,
    togglePlain: () => setPlain(!plain.value),
    restorePlain,
  }
}
