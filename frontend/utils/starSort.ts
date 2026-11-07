import type { Star } from '~/types/api'

export type StarSort = 'release' | 'discovered' | 'added'

export const STAR_SORT_STORAGE_KEY = 'xstream.starSort'

/** Parse persisted sort; unknown values or legacy 'works' fall back to 'release'. */
export function parseStarSort(raw: string | null | undefined): StarSort {
  if (raw === 'discovered' || raw === 'added' || raw === 'release') return raw
  if (raw === 'works') return 'release'
  return 'release'
}

export function parseAddedAt(iso: string | null | undefined): number {
  const t = iso ? Date.parse(iso) : NaN
  return Number.isFinite(t) ? t : 0
}

export function parseReleaseDate(dateStr: string | null | undefined): number {
  if (!dateStr) return 0
  const parts = dateStr.split('/')
  if (parts.length === 3) {
    const y = parseInt(parts[2], 10)
    const m = parseInt(parts[1], 10) - 1
    const d = parseInt(parts[0], 10)
    return Date.UTC(y, m, d)
  }
  return 0
}

export function parseDiscoveredAt(iso: string | null | undefined): number {
  if (!iso) return 0
  const t = Date.parse(iso)
  return Number.isFinite(t) ? t : 0
}

/**
 * Client-side multi-key sort for stars and their titles:
 * - 'release': Newest release date first -> ties broken by newest discovered -> name
 * - 'discovered': Newest discovered on xstream first -> ties broken by release date -> name
 * - 'added': Star follow date (added_at) first -> name
 */
export function sortStarsForDisplay(list: Star[], mode: StarSort): Star[] {
  // First clone each star and sort titles inside according to the chosen mode
  const sortedStars = list.map(star => {
    const titles = [...(star.titles ?? [])]
    if (mode === 'discovered') {
      titles.sort((a, b) => {
        const da = parseDiscoveredAt(a.discovered_at)
        const db = parseDiscoveredAt(b.discovered_at)
        if (da !== db) return db - da
        const ra = parseReleaseDate(a.date)
        const rb = parseReleaseDate(b.date)
        if (ra !== rb) return rb - ra
        return (b.code || '').localeCompare(a.code || '')
      })
    } else {
      // mode === 'release' or mode === 'added'
      titles.sort((a, b) => {
        const ra = parseReleaseDate(a.date)
        const rb = parseReleaseDate(b.date)
        if (ra !== rb) return rb - ra
        const da = parseDiscoveredAt(a.discovered_at)
        const db = parseDiscoveredAt(b.discovered_at)
        if (da !== db) return db - da
        return (b.code || '').localeCompare(a.code || '')
      })
    }
    return { ...star, titles }
  })

  if (mode === 'added') {
    return sortedStars.sort(
      (a, b) => parseAddedAt(b.added_at) - parseAddedAt(a.added_at) || a.name.localeCompare(b.name),
    )
  }

  if (mode === 'discovered') {
    return sortedStars.sort((a, b) => {
      const da = Math.max(0, ...(a.titles?.map(t => parseDiscoveredAt(t.discovered_at)) ?? []))
      const db = Math.max(0, ...(b.titles?.map(t => parseDiscoveredAt(t.discovered_at)) ?? []))
      if (da !== db) return db - da
      const ra = Math.max(0, ...(a.titles?.map(t => parseReleaseDate(t.date)) ?? []))
      const rb = Math.max(0, ...(b.titles?.map(t => parseReleaseDate(t.date)) ?? []))
      if (ra !== rb) return rb - ra
      return a.name.localeCompare(b.name)
    })
  }

  // mode === 'release' (default)
  return sortedStars.sort((a, b) => {
    const ra = Math.max(0, ...(a.titles?.map(t => parseReleaseDate(t.date)) ?? []))
    const rb = Math.max(0, ...(b.titles?.map(t => parseReleaseDate(t.date)) ?? []))
    if (ra !== rb) return rb - ra
    const da = Math.max(0, ...(a.titles?.map(t => parseDiscoveredAt(t.discovered_at)) ?? []))
    const db = Math.max(0, ...(b.titles?.map(t => parseDiscoveredAt(t.discovered_at)) ?? []))
    if (da !== db) return db - da
    return a.name.localeCompare(b.name)
  })
}
