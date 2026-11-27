/**
 * useVideoPlayer — playback status driven by SSE only (no polling)
 *
 * Status updates arrive over the single shared EventSource:
 *   torrent.progress       — throttled 2s push with full status fields; merged locally
 *   torrent.head_ready     — head data ready for playback
 *   torrent.status         — state transitions (checked / finished)
 *   sync.resync_required   — server coalesced a slow client; refetch status once
 */

import type { TorrentStatus } from '~/types/api'
import { onScopeDispose } from 'vue'
import { logInfo, logError } from './useLogger'

export function useVideoPlayer() {
  const config = useRuntimeConfig()
  const status = ref<TorrentStatus | null>(null)
  const loading = ref(false)
  const error = ref('')
  const canplayFired = ref(false)
  let _unsubEvent: (() => void) | null = null
  let _currentHash = ''

  function traceHeaders() {
    return { 'x-trace-id': import.meta.client ? (localStorage.getItem('xstream_trace_id') || '') : '' }
  }

  function mergeStatus(patch: Record<string, any>) {
    status.value = { ...(status.value ?? {}), ...patch } as TorrentStatus
  }

  async function checkHeadReady(hash: string): Promise<boolean> {
    const t0 = performance.now()
    try {
      const res = await $fetch(`/api/check/${hash}`, {
        baseURL: config.public.apiBase,
        headers: traceHeaders(),
      }) as any
      const ok = res.head_ready === true
      logInfo('player', `checkHeadReady ${hash.slice(0, 12)} -> ${ok} (${(performance.now() - t0).toFixed(0)}ms)`)
      return ok
    } catch (e: any) {
      logError('player', `checkHeadReady ${hash.slice(0, 12)} failed: ${e.message || e}`)
      return false
    }
  }

  async function pollStatus(hash: string) {
    try {
      const res = await $fetch(`/torrent/status/${hash}`, {
        baseURL: config.public.apiBase,
        headers: traceHeaders(),
      }) as TorrentStatus
      const prev = status.value
      status.value = res
      if (!prev?.head_ready && res.head_ready) {
        logInfo('player', `status ${hash.slice(0, 12)} head_ready=true progress=${res.progress.toFixed(1)}%`)
      }
      return res
    } catch (e: any) {
      const statusCode = e?.status ?? e?.response?.status
      if (statusCode !== 404) {
        logError('player', `pollStatus ${hash.slice(0, 12)} failed: ${e.message || e}`)
      }
      throw e
    }
  }

  function startPolling(hash: string) {
    stopPolling()
    _currentHash = hash
    logInfo('player', `startStatusSubscription ${hash.slice(0, 12)}`)

    // One initial fetch to populate fields progress events don't carry
    // (name, quality, piece_segments, exact on-disk local_size).
    pollStatus(hash).catch(() => {})

    const { onServerEvent } = useEventSource()
    const unsubProgress = onServerEvent('torrent.progress', (data: any) => {
      if (data.hash !== hash) return
      const prev = status.value
      mergeStatus(data)
      if (!prev?.head_ready && data.head_ready) {
        logInfo('player', `status ${hash.slice(0, 12)} head_ready=true progress=${(data.progress ?? 0).toFixed(1)}%`)
      }
    })
    const unsubHead = onServerEvent('torrent.head_ready', (data: any) => {
      if (data.hash === hash) {
        logInfo('player', `SSE head_ready ${hash.slice(0, 12)}`)
        mergeStatus({ head_ready: true })
      }
    })
    const unsubStatus = onServerEvent('torrent.status', (data: any) => {
      if (data.hash !== hash) return
      mergeStatus({
        state: data.state,
        ...(data.ready !== undefined ? { ready: data.ready } : {}),
      })
    })
    const unsubResync = onServerEvent('sync.resync_required', () => {
      logInfo('player', 'resync required, refetching status once')
      pollStatus(hash).catch(() => {})
    })
    const unsubReconnected = onServerEvent('sse.reconnected', () => {
      logInfo('player', 'SSE reconnected, refetching status once')
      pollStatus(hash).catch(() => {})
    })
    _unsubEvent = () => {
      unsubProgress()
      unsubHead()
      unsubStatus()
      unsubResync()
      unsubReconnected()
    }

    // Ensure cleanup if the calling component is unmounted
    onScopeDispose(stopPolling)
  }

  function stopPolling() {
    if (_unsubEvent) {
      logInfo('player', 'stopStatusSubscription')
      _unsubEvent()
      _unsubEvent = null
    }
    _currentHash = ''
  }

  let cancelActiveWait: (() => void) | null = null

  function cancelWaitForHeadReady() {
    if (cancelActiveWait) {
      cancelActiveWait()
      cancelActiveWait = null
    }
    loading.value = false
  }

  async function waitForHeadReady(hash: string, timeoutSec = 180): Promise<boolean> {
    cancelWaitForHeadReady()
    loading.value = true
    error.value = ''
    const start = Date.now()
    let cancelled = false
    const onCancel = () => { cancelled = true }
    cancelActiveWait = onCancel
    logInfo('player', `waitForHeadReady ${hash.slice(0, 12)} start`)

    // Ensure torrent is added once before waiting.
    // add_torrent is idempotent; if already added it returns immediately.
    try {
      await $fetch('/torrent/add', {
        baseURL: config.public.apiBase,
        method: 'POST',
        headers: traceHeaders(),
        body: { magnet: `magnet:?xt=urn:btih:${hash}` },
      })
    } catch {
      // already added or other error
    }
    if (cancelled) return false

    // Trigger head+tail download so head_ready can be detected.
    try {
      await $fetch('/torrent/resume', {
        baseURL: config.public.apiBase,
        method: 'POST',
        headers: traceHeaders(),
        body: { hash, time: 0, duration: 0 },
      })
    } catch {
      // ignore
    }
    if (cancelled) return false

    if (await checkHeadReady(hash)) {
      if (cancelActiveWait === onCancel) cancelActiveWait = null
      loading.value = false
      logInfo('player', `waitForHeadReady ${hash.slice(0, 12)} success immediately`)
      return true
    }
    if (cancelled) return false

    // Event-driven wait: resolve on SSE, no polling loop.
    const outcome = await new Promise<'ready' | 'timeout' | 'cancelled'>((resolve) => {
      const { onServerEvent } = useEventSource()
      let settled = false
      let timer: ReturnType<typeof setTimeout>
      const done = (res: 'ready' | 'timeout' | 'cancelled') => {
        if (settled) return
        settled = true
        if (cancelActiveWait === cancelNow) cancelActiveWait = null
        unsubs.forEach((fn) => fn())
        clearTimeout(timer)
        resolve(res)
      }
      const cancelNow = () => {
        cancelled = true
        done('cancelled')
      }
      cancelActiveWait = cancelNow
      const unsubs = [
        onServerEvent('torrent.head_ready', (d: any) => {
          if (d.hash === hash) done('ready')
        }),
        onServerEvent('torrent.progress', (d: any) => {
          if (d.hash !== hash) return
          // Keep the loading overlay progress/speed live while waiting.
          mergeStatus(d)
          if (d.head_ready) done('ready')
        }),
        onServerEvent('sync.resync_required', () => {
          checkHeadReady(hash).then((ok) => { if (ok) done('ready') }).catch(() => {})
        }),
        onServerEvent('sse.reconnected', () => {
          checkHeadReady(hash).then((ok) => { if (ok) done('ready') }).catch(() => {})
        }),
      ]
      timer = setTimeout(() => done('timeout'), timeoutSec * 1000)
    })

    loading.value = false
    if (outcome === 'ready') {
      logInfo('player', `waitForHeadReady ${hash.slice(0, 12)} success in ${((Date.now() - start) / 1000).toFixed(1)}s`)
      return true
    }
    if (outcome === 'cancelled') {
      logInfo('player', `waitForHeadReady ${hash.slice(0, 12)} cancelled after ${((Date.now() - start) / 1000).toFixed(1)}s`)
      return false
    }
    error.value = 'Load timeout, please check file integrity'
    logError('player', `waitForHeadReady ${hash.slice(0, 12)} timeout after ${timeoutSec}s`)
    return false
  }

  async function reportSeek(hash: string, time: number, duration: number) {
    if (!hash || !duration || duration === Infinity) return
    try {
      logInfo('player', `reportSeek ${hash.slice(0, 12)} time=${time.toFixed(1)}s`)
      await $fetch('/torrent/seek', {
        baseURL: config.public.apiBase,
        method: 'POST',
        headers: traceHeaders(),
        body: { hash, time, duration },
      })
    } catch (e: any) {
      logError('player', `reportSeek ${hash.slice(0, 12)} failed: ${e.message || e}`)
    }
  }

  async function reportProgress(hash: string, time: number, duration: number) {
    if (!hash || !duration || duration === Infinity) return
    try {
      logInfo('player', `reportProgress ${hash.slice(0, 12)} time=${time.toFixed(1)}s/${duration.toFixed(1)}s`)
      await $fetch('/torrent/progress', {
        baseURL: config.public.apiBase,
        method: 'POST',
        headers: traceHeaders(),
        body: { hash, time, duration },
      })
    } catch (e: any) {
      logError('player', `reportProgress ${hash.slice(0, 12)} failed: ${e.message || e}`)
    }
  }

  async function reportPause(hash: string) {
    if (!hash) return
    try {
      logInfo('player', `reportPause ${hash.slice(0, 12)}`)
      await $fetch('/torrent/pause', {
        baseURL: config.public.apiBase,
        method: 'POST',
        headers: traceHeaders(),
        body: { hash, time: 0, duration: 0 },
      })
    } catch (e: any) {
      logError('player', `reportPause ${hash.slice(0, 12)} failed: ${e.message || e}`)
    }
  }

  let lastResumeHash = ''
  let lastResumeAt = 0

  async function reportResume(hash: string, time: number, duration: number) {
    if (!hash || !duration || duration === Infinity) return
    const now = Date.now()
    if (hash === lastResumeHash && now - lastResumeAt < 1000) return
    lastResumeHash = hash
    lastResumeAt = now
    try {
      logInfo('player', `reportResume ${hash.slice(0, 12)} time=${time.toFixed(1)}s/${duration.toFixed(1)}s`)
      await $fetch('/torrent/resume', {
        baseURL: config.public.apiBase,
        method: 'POST',
        headers: traceHeaders(),
        body: { hash, time, duration },
      })
    } catch (e: any) {
      logError('player', `reportResume ${hash.slice(0, 12)} failed: ${e.message || e}`)
    }
  }

  function formatSpeed(rate: number): string {
    if (rate > 1024 * 1024) return `${(rate / 1024 / 1024).toFixed(1)} MB/s`
    if (rate > 1024) return `${(rate / 1024).toFixed(1)} KB/s`
    return `${rate} B/s`
  }

  return {
    status,
    loading,
    error,
    canplayFired,
    checkHeadReady,
    pollStatus,
    startPolling,
    stopPolling,
    waitForHeadReady,
    cancelWaitForHeadReady,
    reportSeek,
    reportProgress,
    reportPause,
    reportResume,
    formatSpeed,
  }
}
