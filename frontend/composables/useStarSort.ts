import { parseStarSort, STAR_SORT_STORAGE_KEY, type StarSort } from '~/utils/starSort'

/**
 * Home shelf sort preference. Always bootstraps as Latest ('works') for SSR,
 * then re-reads localStorage on mount so hydration cannot stick on Latest while
 * storage says Added.
 */
export function useStarSort() {
  const starSort = ref<StarSort>('works')
  let hydrated = false

  function readStorage(): StarSort {
    if (!import.meta.client) return 'works'
    try {
      return parseStarSort(localStorage.getItem(STAR_SORT_STORAGE_KEY))
    } catch {
      return 'works'
    }
  }

  function hydrateFromStorage() {
    if (!import.meta.client || hydrated) return
    hydrated = true
    starSort.value = readStorage()
  }

  onMounted(hydrateFromStorage)

  watch(starSort, (mode) => {
    if (!import.meta.client) return
    try {
      localStorage.setItem(STAR_SORT_STORAGE_KEY, mode)
    } catch {
      // Ignore a full or blocked store; the choice still applies this visit.
    }
  })

  return { starSort, hydrateFromStorage }
}
