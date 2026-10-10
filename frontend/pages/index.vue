<template>
  <div class="min-h-screen bg-void">
    <AppHeader :offline="health != null && health.status !== 'ok'">
      <template #actions>
        <NuxtLink to="/search" class="btn-icon" title="Search" aria-label="Search">
          <svg width="19" height="19" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <circle cx="11" cy="11" r="7.5" />
            <line x1="21" y1="21" x2="16.5" y2="16.5" />
          </svg>
        </NuxtLink>
        <button class="btn-icon" title="Follow a star" aria-label="Follow a star" @click="addOpen = true">
          <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round">
            <line x1="12" y1="5" x2="12" y2="19" />
            <line x1="5" y1="12" x2="19" y2="12" />
          </svg>
        </button>
        <EventPanel />
        <CachePanel :stars="displayStars" />
        <button
          class="btn btn-sm ml-1 sm:ml-2 !px-3 sm:!px-4"
          :class="syncRunning ? 'btn-secondary !opacity-100' : 'btn-dark'"
          :disabled="syncRunning"
          title="Sync new releases"
          @click="startSync"
        >
          <svg
            width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"
            :class="{ 'animate-spin': syncRunning }"
          >
            <polyline points="23 4 23 10 17 10" />
            <path d="M20.49 15a9 9 0 1 1-2.12-9.36L23 10" />
          </svg>
          <span v-if="syncRunning" class="tabular-nums">{{ syncProgressText || 'Syncing' }}</span>
          <span v-else class="hidden sm:inline">Refresh</span>
        </button>
      </template>
      <StarNav :stars="displayStars" />
    </AppHeader>

    <main class="pt-[calc(env(safe-area-inset-top)+128px)] sm:pt-[calc(env(safe-area-inset-top)+140px)] pb-32">
      <div class="max-w-7xl mx-auto px-4 sm:px-6">
        <!-- Large title -->
        <div class="mb-10 sm:mb-14 px-1">
          <h1 class="text-[34px] sm:text-[44px] font-bold text-foreground leading-[1.05]">Library</h1>
          <p class="mt-1.5 text-[15px] sm:text-[17px] text-foreground-muted tabular-nums min-h-[1.5em]">
            <template v-if="pending">Loading…</template>
            <template v-else-if="!error">{{ displayStars.length }} stars · {{ titleCount }} titles</template>
          </p>
        </div>

        <!-- Loading skeletons -->
        <div v-if="pending" class="space-y-16 md:space-y-24">
          <StarCardSkeleton v-for="n in 2" :key="n" />
        </div>

        <!-- Error -->
        <div v-else-if="error" class="text-center py-32">
          <div class="inline-flex items-center justify-center w-14 h-14 rounded-full bg-danger/10 text-danger mb-5">
            <svg width="26" height="26" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
              <circle cx="12" cy="12" r="10" />
              <line x1="12" y1="8" x2="12" y2="12" />
              <line x1="12" y1="16" x2="12.01" y2="16" />
            </svg>
          </div>
          <p class="text-[19px] font-semibold text-foreground">Couldn't load your library</p>
          <p class="mt-1 text-[15px] text-foreground-muted">The server may be restarting.</p>
          <button class="btn btn-secondary mt-6" @click="refreshNuxtData('stars')">Try Again</button>
        </div>

        <!-- Empty state -->
        <div v-else-if="displayStars.length === 0" class="text-center py-32">
          <p class="text-[22px] font-bold text-foreground">No stars yet</p>
          <p class="mt-1.5 text-[15px] text-foreground-muted">Follow someone to start tracking their releases.</p>
          <div class="mt-7 flex items-center justify-center gap-2.5">
            <button class="btn btn-primary" @click="addOpen = true">Follow a Star</button>
            <NuxtLink to="/search" class="btn btn-secondary">Search</NuxtLink>
          </div>
        </div>

        <!-- Star shelves -->
        <div v-else class="space-y-16 md:space-y-24">
          <div
            v-for="(star, index) in displayStars"
            :id="`star-${star.code.toLowerCase()}`"
            :key="star.code"
            v-observe
            :data-code="star.code"
            class="star-section scroll-mt-[calc(env(safe-area-inset-top)+116px)]"
          >
            <StarCard
              v-if="visibleCodes.has(star.code)"
              :star="star"
              :index="index"
              @play="openVideo"
              @deleted="onStarDeleted"
            />
            <StarCardSkeleton v-else />
          </div>
        </div>
      </div>
    </main>

    <AddStarSheet v-model:open="addOpen" :stars="displayStars" @jump="scrollToStar" />
    <VideoModal v-model:open="modalOpen" :hash="activeHash" :code="activeCode" :star-code="activeStarCode" />

    <SyncToast
      :visible="toastVisible"
      :state="toastState"
      :title="toastTitle"
      :detail="toastDetail"
      :progress-text="toastProgressText"
      :fraction="toastFraction"
      @dismiss="dismissToast"
    />
  </div>
</template>

<script setup lang="ts">
interface HealthResponse {
  status: string
}

const config = useRuntimeConfig()
const { data: health } = useFetch<HealthResponse>('/api/health', { baseURL: config.public.apiBase, server: false })
const { stars, pending, error } = useStars()

const deletedCodes = ref<Set<string>>(new Set())
// VR / multi-star works are filtered at collection time (scrapers/v2/
// filters.py) and never reach the API; the backend returns every title
// newest-first per star and orders stars by newest work, so the API order
// is the display order.
const displayStars = computed(() =>
  (stars.value ?? []).filter(s => !deletedCodes.value.has(s.code))
)

const titleCount = computed(() =>
  displayStars.value.reduce((n, s) => n + (s.titles?.length ?? 0), 0)
)

const visibleCodes = ref<Set<string>>(new Set())
const addOpen = ref(false)

const modalOpen = ref(false)
const activeHash = ref('')
const activeCode = ref('')
const activeStarCode = ref('')

function scrollToStar(code: string) {
  const el = document.getElementById(`star-${code.toLowerCase()}`)
  if (el) {
    el.scrollIntoView({ behavior: 'smooth', block: 'start' })
  }
}

function onStarDeleted(code: string) {
  deletedCodes.value.add(code)
  track('delete_star', { code })
  addLog({ kind: 'action', title: `Deleted star ${code}`, state: 'success' })
}

function openVideo(magnet: string, code = '', starCode = '') {
  const match = magnet.match(/xt=urn:btih:([a-f0-9]{40})/i)
  if (match) {
    activeHash.value = match[1].toLowerCase()
    activeCode.value = code
    activeStarCode.value = starCode
    modalOpen.value = true
  }
}

const syncRunning = ref(false)
const syncError = ref('')
const { track } = useTrack()
const { add: addLog } = useEventLog()
const { getSyncStatus } = useApi()

async function fetchSyncStatus(silent = false) {
  try {
    const status = await getSyncStatus()
    syncRunning.value = status.running
    if (!silent && status.last_error) {
      syncError.value = status.last_error
    }
  } catch (e: any) {
    if (!silent) syncError.value = e?.message || 'Failed to check sync status'
  }
}

const toastVisible = ref(false)
const toastState = ref<'running' | 'success' | 'error'>('running')
const toastTitle = ref('')
const toastDetail = ref('')
const toastProgressText = ref('')
const toastFraction = ref(0)
const syncProgressText = ref('')
let toastTimer: ReturnType<typeof setTimeout> | null = null

function showRunningToast(title: string, detail = '', progressText = '', fraction = 0.02) {
  if (toastTimer) { clearTimeout(toastTimer); toastTimer = null }
  toastState.value = 'running'
  toastTitle.value = title
  toastDetail.value = detail
  toastProgressText.value = progressText
  toastFraction.value = fraction
  toastVisible.value = true
}

function finishToast(title: string, detail: string, state: 'success' | 'error') {
  toastState.value = state
  toastTitle.value = title
  toastDetail.value = detail
  toastProgressText.value = ''
  toastFraction.value = 1
  toastVisible.value = true
  if (toastTimer) clearTimeout(toastTimer)
  toastTimer = setTimeout(() => { toastVisible.value = false }, state === 'error' ? 6000 : 4000)
}

function dismissToast() {
  toastVisible.value = false
  if (toastTimer) clearTimeout(toastTimer)
}

// Live sync progress pushed via SSE sync.progress events.
// Phases: prepare → fetch (per star) → covers → write (per star).
// Since fetch/covers/write are pipelined per star, events interleave —
// keep the bar monotonic so it never jumps backwards mid-run.
let syncPeakFraction = 0
function syncBar(fraction: number): number {
  syncPeakFraction = Math.max(syncPeakFraction, fraction)
  return syncPeakFraction
}
function handleSyncProgress(data: any) {
  switch (data.phase) {
    case 'prepare':
      showRunningToast('Syncing…', data.detail || 'Preparing')
      break
    case 'fetch': {
      const done = data.done ?? 0
      const total = data.total ?? 0
      const detail = data.star
        ? (data.ok ? `${data.star} — ${data.titles} titles` : `${data.star} — fetch failed`)
        : 'Fetching ijavtorrent + sukebei RSS'
      showRunningToast('Fetching stars', detail, `${done}/${total}`, syncBar(total ? (done / total) * 0.8 : 0.02))
      syncProgressText.value = total ? `${done}/${total}` : ''
      break
    }
    case 'covers':
      showRunningToast('Downloading covers', `${data.count ?? 0} new covers`, '', syncBar(0.85))
      break
    case 'write': {
      const done = data.done ?? 0
      const total = data.total ?? 0
      const detail = data.star ? `${data.star}: +${data.new ?? 0} new` : ''
      showRunningToast('Writing to database', detail, total ? `${done}/${total}` : '', syncBar(0.85 + (total ? (done / total) * 0.13 : 0)))
      break
    }
  }
}

async function startSync() {
  if (syncRunning.value) return
  syncError.value = ''

  try {
    const res = await $fetch('/api/stars/sync', {
      baseURL: config.public.apiBase,
      method: 'POST',
    }) as any

    if (res.status === 'started' || res.status === 'running') {
      syncRunning.value = true
      syncProgressText.value = ''
      syncPeakFraction = 0
      showRunningToast('Syncing…', 'Starting sync')
    }
  } catch (e: any) {
    syncError.value = e?.message || 'Failed to start sync'
  }
}

async function clearStarsServiceWorkerCache() {
  if (typeof window !== 'undefined' && 'caches' in window) {
    try {
      await caches.delete('stars-cache')
    } catch {
      // ignore
    }
  }
}

function handleSyncCompleted(data: any) {
  syncRunning.value = false
  syncProgressText.value = ''
  const totalNew = data.total_new ?? 0
  const elapsed = data.elapsed ?? 0
  const failed: string[] = data.failed ?? []
  if (failed.length > 0) {
    finishToast(
      `Sync incomplete — ${failed.length} star${failed.length > 1 ? 's' : ''} unreachable`,
      `${totalNew} new title${totalNew === 1 ? '' : 's'} synced in ${elapsed}s; failed: ${failed.join(', ')}`,
      'error'
    )
  } else if (totalNew > 0) {
    finishToast(
      `${totalNew} new title${totalNew > 1 ? 's' : ''} added`,
      `Synced in ${elapsed}s`,
      'success'
    )
  } else {
    finishToast('All caught up', `Checked in ${elapsed}s — no new releases`, 'success')
  }
  clearStarsServiceWorkerCache()
  refreshNuxtData('stars')
}

function handleSyncError(data: any) {
  syncRunning.value = false
  syncProgressText.value = ''
  syncError.value = data.error || 'Sync failed'
  finishToast('Sync failed', data.error || '', 'error')
}

function handleStarReady() {
  refreshNuxtData('stars')
}

// SSE subscriptions
onMounted(() => {
  const { onServerEvent } = useEventSource()
  const unsubs: (() => void)[] = []

  fetchSyncStatus(true)

  unsubs.push(onServerEvent('sync.started', () => {
    syncRunning.value = true
    syncProgressText.value = ''
    showRunningToast('Syncing…', 'Starting sync')
  }))

  unsubs.push(onServerEvent('sync.progress', handleSyncProgress))
  unsubs.push(onServerEvent('sync.completed', handleSyncCompleted))
  unsubs.push(onServerEvent('sync.error', handleSyncError))
  unsubs.push(onServerEvent('star.ready', handleStarReady))
  // Server coalesced our event queue (slow client) — refetch state once.
  unsubs.push(onServerEvent('sync.resync_required', () => {
    fetchSyncStatus(true)
    refreshNuxtData('stars')
  }))

  onUnmounted(() => {
    unsubs.forEach((fn) => fn())
    if (toastTimer) clearTimeout(toastTimer)
  })
})

// Virtual rendering with IntersectionObserver. Sections mount whenever the
// client fetch delivers data, so ref-array + onMounted/watch wiring races
// (and silently observes nothing when stars load after mount). A directive
// observes each section at its own mount — immune to that timing.
let observer: IntersectionObserver | null = null
if (import.meta.client) {
  observer = new IntersectionObserver((entries) => {
    entries.forEach((entry) => {
      const code = entry.target.getAttribute('data-code')
      if (code && entry.isIntersecting && !visibleCodes.value.has(code)) {
        visibleCodes.value.add(code)
        track('star_view', { star_code: code })
      }
    })
  }, {
    rootMargin: '600px',
    threshold: 0,
  })
}

const vObserve = {
  mounted(el: HTMLElement) { observer?.observe(el) },
  unmounted(el: HTMLElement) { observer?.unobserve(el) },
}

onUnmounted(() => {
  if (observer) observer.disconnect()
})

</script>

<style scoped>
/*
 * Virtual rendering mounts sections as they approach the viewport but never
 * unmounts them — after a full-catalog scroll thousands of <img> nodes stay
 * live. content-visibility lets the browser skip layout/paint for off-screen
 * sections; contain-intrinsic-size reserves an approximate box so the
 * scrollbar doesn't jump. The real height is remembered after first render
 * ("auto" prefix), so this estimate only applies to never-rendered sections.
 */
.star-section {
  content-visibility: auto;
  contain-intrinsic-size: auto 900px;
}
</style>
