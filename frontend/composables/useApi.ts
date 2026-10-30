import type {
  CreatorInjectResult,
  FilesConfigResponse,
  PlayDirectResponse,
  RecentPlay,
  XInjectResult,
} from '~/types/api'
import { getTraceId, syncTraceIdFromResponse } from './useLogger'

function _headers() {
  return { 'x-trace-id': getTraceId() }
}

export function useApi() {
  const config = useRuntimeConfig()

  async function addTorrent(magnet: string) {
    const res = await $fetch.raw('/torrent/add', {
      baseURL: config.public.apiBase,
      method: 'POST',
      headers: _headers(),
      body: { magnet },
    })
    syncTraceIdFromResponse(res)
    return res._data
  }

  async function getCacheMetrics() {
    const res = await $fetch.raw('/api/cache/metrics', {
      baseURL: config.public.apiBase,
      headers: _headers(),
    })
    syncTraceIdFromResponse(res)
    return res._data
  }

  async function getCacheItems() {
    const res = await $fetch.raw('/api/cache', {
      baseURL: config.public.apiBase,
      headers: _headers(),
    })
    syncTraceIdFromResponse(res)
    return res._data
  }

  async function deleteCache(hash: string) {
    const res = await $fetch.raw(`/api/cache/${hash}`, {
      baseURL: config.public.apiBase,
      method: 'DELETE',
      headers: _headers(),
    })
    syncTraceIdFromResponse(res)
    return res._data
  }

  async function deleteStar(code: string) {
    const res = await $fetch.raw(`/api/stars/${code}`, {
      baseURL: config.public.apiBase,
      method: 'DELETE',
      headers: _headers(),
    })
    syncTraceIdFromResponse(res)
    return res._data
  }

  async function likeTitle(code: string, liked: boolean) {
    const res = await $fetch.raw('/api/stars/like', {
      baseURL: config.public.apiBase,
      method: 'POST',
      headers: _headers(),
      body: { code, liked },
    })
    syncTraceIdFromResponse(res)
    return res._data
  }

  async function getSyncStatus() {
    const res = await $fetch.raw('/api/stars/sync', {
      baseURL: config.public.apiBase,
      headers: _headers(),
    })
    syncTraceIdFromResponse(res)
    return res._data as { running: boolean; elapsed?: number; last_error?: string | null }
  }

  async function getXAgentBrief(staleHours = 72) {
    const res = await $fetch.raw(`/api/social/x/agent-brief?stale_hours=${staleHours}`, {
      baseURL: config.public.apiBase,
      headers: _headers(),
    })
    syncTraceIdFromResponse(res)
    return res._data as {
      prompt_markdown: string
      work_queue: { stars_needing_check: number; creators_stale: string[] }
      endpoints: Record<string, string>
    }
  }

  async function injectX(star: string | null, content: string) {
    const res = await $fetch.raw('/api/social/x', {
      baseURL: config.public.apiBase,
      method: 'POST',
      headers: _headers(),
      body: { star, content },
    })
    syncTraceIdFromResponse(res)
    return res._data as { updated: number; results: XInjectResult[] }
  }

  /**
   * Pornographic creators (owner's adult X follows, not library stars). Injected by
   * the external bot with the same payload shapes as stars; 10 posts each.
   */
  async function injectCreators(content: string | Record<string, unknown>) {
    const res = await $fetch.raw('/api/social/x/creators', {
      baseURL: config.public.apiBase,
      method: 'POST',
      headers: _headers(),
      body: { content },
    })
    syncTraceIdFromResponse(res)
    return res._data as { updated: number; results: CreatorInjectResult[] }
  }

  async function unfollowCreator(handle: string) {
    const res = await $fetch.raw(`/api/social/x/creators/${handle}`, {
      baseURL: config.public.apiBase,
      method: 'DELETE',
      headers: _headers(),
    })
    syncTraceIdFromResponse(res)
    return res._data as { handle: string; deleted: boolean }
  }

  async function playDirect(magnet: string) {
    const res = await $fetch.raw('/api/play/direct', {
      baseURL: config.public.apiBase,
      method: 'POST',
      headers: _headers(),
      body: { magnet },
    })
    syncTraceIdFromResponse(res)
    return res._data as PlayDirectResponse
  }

  async function listRecentPlays() {
    const res = await $fetch.raw('/api/play/recent', {
      baseURL: config.public.apiBase,
      headers: _headers(),
    })
    syncTraceIdFromResponse(res)
    return ((res._data as { items?: RecentPlay[] } | undefined)?.items ?? []) as RecentPlay[]
  }

  async function deleteRecentPlay(hash: string) {
    const res = await $fetch.raw(`/api/play/${hash}`, {
      baseURL: config.public.apiBase,
      method: 'DELETE',
      headers: _headers(),
    })
    syncTraceIdFromResponse(res)
    return res._data as { ok: boolean }
  }

  async function filesConfig() {
    const res = await $fetch.raw('/api/files/config', {
      baseURL: config.public.apiBase,
      headers: _headers(),
    })
    syncTraceIdFromResponse(res)
    return res._data as FilesConfigResponse
  }

  return {
    getXAgentBrief,
    injectX,
    injectCreators,
    unfollowCreator,
    addTorrent,
    getCacheMetrics,
    getCacheItems,
    deleteCache,
    deleteStar,
    likeTitle,
    getSyncStatus,
    playDirect,
    listRecentPlays,
    deleteRecentPlay,
    filesConfig,
  }
}
