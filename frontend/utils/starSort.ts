import type { Star } from '~/types/api'

export type StarSort = 'works' | 'added'

export const STAR_SORT_STORAGE_KEY = 'xstream.starSort'

/** Parse persisted sort; unknown values fall back to newest-work order. */
export function parseStarSort(raw: string | null | undefined): StarSort {
  return raw === 'added' || raw === 'works' ? raw : 'works'
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
 * Client-side multi-key sort for display:
 * - 'works': Multi-sort keys on release:
 *     1. Release date DESC (作品发布日期)
 *     2. Discovery date on xstream (discovered_at / created_at) DESC (作品发现日志)
 *     3. Star name ASC
 * - 'added': Followed date (added_at) DESC -> star name ASC
 */
export function sortStarsForDisplay(list: Star[], mode: StarSort): Star[] {
  // Titles within each star are ordered by multi-sort keys: release date -> discovered_at -> code
  const sorted = list.map(star => {
    const titles = [...(star.titles ?? [])]
    titles.sort((a, b) => {
      const ra = parseReleaseDate(a.date)
      const rb = parseReleaseDate(b.date)
      if (ra !== rb) return rb - ra
      const da = parseDiscoveredAt(a.discovered_at)
      const db = parseDiscoveredAt(b.discovered_at)
      if (da !== db) return db - da
      return (b.code || '').localeCompare(a.code || '')
    })
    return { ...star, titles }
  })

  if (mode === 'added') {
    return sorted.sort(
      (a, b) => parseAddedAt(b.added_at) - parseAddedAt(a.added_at) || a.name.localeCompare(b.name),
    )
  }

  // 'works': Multi-sort keys on release
  return sorted.sort((a, b) => {
    const ra = parseReleaseDate(a.titles?.[0]?.date)
    const rb = parseReleaseDate(b.titles?.[0]?.date)
    if (ra !== rb) return rb - ra
    const da = parseDiscoveredAt(a.titles?.[0]?.discovered_at)
    const db = parseDiscoveredAt(b.titles?.[0]?.discovered_at)
    if (da !== db) return db - da
    return a.name.localeCompare(b.name)
  })
}
