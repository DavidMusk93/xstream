import type { CreatorProfile } from '~/types/api'

/**
 * Body creators — X accounts the owner follows that are not library stars.
 *
 * Injected by the external bot (POST /api/social/x/creators), 10 posts each.
 * Fetched on demand (the overlay is the only consumer) and invalidated by the
 * `creator.social` SSE event; never part of the /api/stars payload.
 */
export function useCreators() {
  const config = useRuntimeConfig()

  const { data, pending, error, refresh } = useFetch<{ count: number; creators: CreatorProfile[] }>(
    '/api/social/x/creators',
    { baseURL: config.public.apiBase, key: 'creators', server: false },
  )

  const creators = computed<CreatorProfile[]>(() => data.value?.creators ?? [])

  return { creators, pending, error, refresh }
}
