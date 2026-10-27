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
        <NuxtLink to="/play" class="btn-icon" title="Play a magnet" aria-label="Play a magnet">
          <svg width="17" height="17" viewBox="0 0 24 24" fill="currentColor">
            <path d="M7 4.5v15l12.5-7.5z" />
          </svg>
        </NuxtLink>
        <NuxtLink to="/files" class="btn-icon" title="Files" aria-label="Files">
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z" />
          </svg>
        </NuxtLink>
        <button class="btn-icon" title="Follow a star" aria-label="Follow a star" @click="addOpen = true">
          <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round">
            <line x1="12" y1="5" x2="12" y2="19" />
            <line x1="5" y1="12" x2="19" y2="12" />
          </svg>
        </button>
        <button class="btn-icon" title="X posts" aria-label="X posts" @click="openSocial('')">
          <XGlyph class="w-[16px] h-[16px]" />
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
      <StarNav :stars="displayStars" :active="navActive" @select="navActive = $event" />
    </AppHeader>

    <main class="pt-[calc(env(safe-area-inset-top)+128px)] sm:pt-[calc(env(safe-area-inset-top)+140px)] pb-32">
      <div class="max-w-7xl mx-auto px-4 sm:px-6">
        <!-- Large title -->
        <div class="relative mb-14 sm:mb-20 px-1">
          <div class="pointer-events-none absolute -top-40 -left-24 w-[640px] max-w-[120vw] h-[420px] rounded-full bg-[radial-gradient(closest-side,rgba(255,55,95,0.10),transparent)]" aria-hidden="true" />
          <p class="eyebrow rise relative">
            <span class="text-accent">00</span>
            <span>Your collection</span>
            <span class="h-px w-10 bg-black/10" />
          </p>
          <h1 class="rise relative mt-3 text-[40px] sm:text-[56px] font-bold text-foreground leading-[1.02]" style="--rise-delay: 0.08s">
            Library
          </h1>
          <dl
            v-if="!error"
            class="rise relative mt-8 sm:mt-10 flex divide-x divide-black/[0.08] tabular-nums"
            style="--rise-delay: 0.16s"
          >
            <div v-for="stat in stats" :key="stat.label" class="pr-6 sm:pr-10 pl-6 sm:pl-10 first:pl-0">
              <dt class="sr-only">{{ stat.label }}</dt>
              <dd class="text-[28px] sm:text-[36px] font-semibold text-foreground leading-none tracking-tight">
                <span v-if="pending" class="inline-block w-12 h-7 rounded-md bg-black/[0.06] animate-pulse align-middle" />
                <template v-else>{{ stat.value }}</template>
              </dd>
              <dd class="mt-2 text-[13px] text-foreground-muted" aria-hidden="true">{{ stat.label }}</dd>
            </div>
          </dl>
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
          <button class="btn btn-secondary mt-6" @click="refreshLibrary()">Try Again</button>
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
              @social="openSocial"
            />
            <StarCardSkeleton v-else />
          </div>
        </div>
      </div>
    </main>

    <AddStarSheet v-model:open="addOpen" :stars="displayStars" @jump="scrollToStar" @added="onStarAdded" />
    <XSocialOverlay
      v-model:open="socialOpen"
      v-model:filter="socialFilter"
      :stars="displayStars"
      :creators="creators"
      @inject="openInject"
      @creators-changed="refreshCreators"
    />
    <XInjectSheet v-model:open="injectOpen" v-model:target="injectTarget" :stars="displayStars" />
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
const { stars, pending, error, refreshLibrary, patchStarAdded } = useStars()
// Body creators (accounts the owner follows on X, injected by the bot) are a
// separate group from the library stars — see docs/design/x-inject.md.
const { creators, refresh: refreshCreators } = useCreators()

const deletedCodes = ref<Set<string>>(new Set())
// VR / multi-star works are filtered at collection time (scrapers/v2/
// filters.py) and never reach the API; the backend returns every title
// newest-first per star and orders stars by newest work, so the API order
// is the display order.
const displayStars = computed(() =>
  (stars.value ?? []).filter(s => !deletedCodes.value.has(s.code))
)

// Title dates arrive as D/M/YYYY (see fmtDate in StarCard).
function titleTime(date?: string): number {
  const p = date?.split('/')
  return p?.length === 3 ? Date.UTC(+p[2], +p[1] - 1, +p[0]) : 0
}

const stats = computed(() => {
  const titles = displayStars.value.flatMap(s => s.titles ?? [])
  const weekAgo = Date.now() - 7 * 24 * 3600 * 1000
  return [
    { label: 'Stars', value: displayStars.value.length.toLocaleString() },
    { label: 'Titles', value: titles.length.toLocaleString() },
    { label: 'This week', value: titles.filter(t => titleTime(t.date) >= weekAgo).length.toLocaleString() },
  ]
})

const visibleCodes = ref<Set<string>>(new Set())
const addOpen = ref(false)
const injectOpen = ref(false)
const injectTarget = ref('')
const socialOpen = ref(false)
const socialFilter = ref('')

function openInject(code: string) {
  // The inject sheet (z-90) sits under the social overlay (z-95): close the
  // overlay so the sheet is interactive; reopening the overlay shows the
  // injected posts after the SSE refetch.
  socialOpen.value = false
  injectTarget.value = code
  injectOpen.value = true
}

function openSocial(code: string) {
  socialFilter.value = code
  socialOpen.value = true
}

const modalOpen = ref(false)
const activeHash = ref('')
const activeCode = ref('')
const activeStarCode = ref('')

function scrollToStar(code: string) {
  const el = document.getElementById(`star-${code.toLowerCase()}`)
  if (el) {
    el.scrollIntoView({ behavior: 'smooth', block: 'start' })
    return true
  }
  return false
}

/** Virtual shelf renders StarCard only after intersection — follow must not wait for scroll. */
function revealStar(code: string, scroll = false) {
  visibleCodes.value.add(code)
  if (!scroll) return
  nextTick(() => {
    requestAnimationFrame(() => {
      if (!scrollToStar(code)) {
        const stop = watch(
          () => displayStars.value.some(s => s.code === code),
          (ok) => {
            if (!ok) return
            nextTick(() => {
              scrollToStar(code)
              stop()
            })
          },
          { immediate: true },
        )
      }
    })
  })
}

const scrollAfterRefreshCode = ref<string | null>(null)

function onStarAdded(payload: { code: string; name: string; handle?: string }) {
  patchStarAdded(payload)
  scrollAfterRefreshCode.value = payload.code
  revealStar(payload.code, true)
  refreshLibrary().catch(() => {})
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
  refreshLibrary().catch(() => {})
}

function handleSyncError(data: any) {
  syncRunning.value = false
  syncProgressText.value = ''
  syncError.value = data.error || 'Sync failed'
  finishToast('Sync failed', data.error || '', 'error')
}

async function handleStarAddedEvent(data: { code?: string; name?: string; handle?: string }) {
  if (data?.code && data?.name) {
    patchStarAdded({
      code: data.code,
      name: data.name,
      handle: data.handle,
    })
    revealStar(data.code, scrollAfterRefreshCode.value === data.code)
  }
  try {
    await refreshLibrary()
  } catch {
    // optimistic row already on screen
  }
}

async function handleStarReady(data?: { code?: string }) {
  try {
    await refreshLibrary()
  } catch {
    return
  }
  const code = data?.code ?? scrollAfterRefreshCode.value
  if (code) {
    revealStar(code, scrollAfterRefreshCode.value === code)
    if (scrollAfterRefreshCode.value === code) {
      scrollAfterRefreshCode.value = null
    }
  }
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
  unsubs.push(onServerEvent('star.added', handleStarAddedEvent))
  unsubs.push(onServerEvent('star.ready', handleStarReady))
  // Injected X posts (this tab, another device, or an agent via the API).
  unsubs.push(onServerEvent('star.social', () => { refreshLibrary().catch(() => {}) }))
  // Body creators live outside /api/stars — refresh their own feed.
  unsubs.push(onServerEvent('creator.social', () => refreshCreators()))
  // Server coalesced our event queue (slow client) — refetch state once.
  unsubs.push(onServerEvent('sync.resync_required', () => {
    fetchSyncStatus(true)
    refreshLibrary().catch(() => {})
    refreshCreators()
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

// Active star for StarNav: the section crossing a band at 30–40% of the
// viewport. Same directive, same mount-time wiring.
const navActive = ref('')
let bandObserver: IntersectionObserver | null = null
if (import.meta.client) {
  bandObserver = new IntersectionObserver((entries) => {
    for (const entry of entries) {
      const code = entry.target.getAttribute('data-code')
      if (code && entry.isIntersecting) navActive.value = code
    }
  }, { rootMargin: '-30% 0px -60% 0px' })
}

const vObserve = {
  mounted(el: HTMLElement) {
    observer?.observe(el)
    bandObserver?.observe(el)
  },
  unmounted(el: HTMLElement) {
    observer?.unobserve(el)
    bandObserver?.unobserve(el)
  },
}

onUnmounted(() => {
  observer?.disconnect()
  bandObserver?.disconnect()
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
