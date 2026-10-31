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

/** Client-side reorder for Added; Latest keeps API order. */
export function sortStarsForDisplay(list: Star[], mode: StarSort): Star[] {
  if (mode !== 'added') return list
  return [...list].sort(
    (a, b) => parseAddedAt(b.added_at) - parseAddedAt(a.added_at) || a.name.localeCompare(b.name),
  )
}
