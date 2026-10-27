import type { Star } from '~/types/api'

export async function clearStarsServiceWorkerCache() {
  if (typeof window === 'undefined' || !('caches' in window)) return
  try {
    await caches.delete('stars-cache')
  } catch {
    // ignore
  }
}

/** Minimal row so a new follow appears on the shelf before bg sync finishes. */
export function emptyStarRow(payload: {
  name: string
  code: string
  handle?: string
}): Star {
  return {
    name: payload.name,
    jp: payload.name,
    handle: payload.handle ?? '',
    code: payload.code,
    type: 'solo',
    titles: [],
  }
}

export function useStars() {
  const config = useRuntimeConfig()

  // Client-only fetch: SSR must not block on /api/stars. If the backend is
  // slow or mid-restart, an awaited SSR fetch leaves the browser with no HTML
  // at all (white screen); with server:false the shell + skeleton render
  // instantly and data fills in when the client fetch completes.
  const { data: stars, pending, error, refresh: nuxtRefresh } = useFetch<Star[]>('/api/stars', {
    baseURL: config.public.apiBase,
    key: 'stars',
    server: false,
  })

  /** Force a network reload (SW + 304-safe). Assigns into the shared stars ref. */
  async function refreshLibrary() {
    await clearStarsServiceWorkerCache()
    const bust = Date.now()
    const rows = await $fetch<Star[]>(`/api/stars?_=${bust}`, {
      baseURL: config.public.apiBase,
      headers: { 'Cache-Control': 'no-cache', Pragma: 'no-cache' },
    })
    stars.value = rows
    return rows
  }

  /** Show the new star immediately; server list reconciles on refreshLibrary. */
  function patchStarAdded(payload: { name: string; code: string; handle?: string }) {
    const list = stars.value ? [...stars.value] : []
    if (list.some(s => s.code === payload.code)) return
    list.unshift(emptyStarRow(payload))
    stars.value = list
  }

  if (import.meta.client) {
    onMounted(() => {
      if (error.value) {
        refreshLibrary().catch(() => nuxtRefresh())
      }
    })
  }

  return {
    stars,
    pending,
    error,
    refreshLibrary,
    patchStarAdded,
  }
}
