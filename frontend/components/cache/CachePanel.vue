<template>
  <div ref="rootRef" class="sm:relative">
    <button
      class="btn-icon relative"
      :class="isOpen ? 'bg-black/[0.06]' : ''"
      title="Downloads"
      aria-label="Downloads"
      :aria-expanded="isOpen"
      @click="isOpen = !isOpen"
    >
      <svg width="19" height="19" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
        <path d="M12 3v12" />
        <polyline points="7 10 12 15 17 10" />
        <path d="M5 21h14" />
      </svg>
      <span v-if="activeCount > 0" class="absolute top-2 right-2 w-2 h-2 rounded-full bg-success ring-2 ring-white" />
    </button>

    <Transition name="pop">
      <div
        v-if="isOpen"
        class="popover fixed sm:absolute left-3 right-3 sm:left-auto sm:right-0 top-[calc(env(safe-area-inset-top)+60px)] sm:top-full sm:mt-2 sm:w-[420px] max-h-[calc(100dvh-84px)] origin-top-right overflow-hidden flex flex-col z-50"
      >
        <!-- Header -->
        <div class="px-5 pt-5 pb-4">
          <div class="flex items-baseline justify-between gap-3">
            <h3 class="text-[17px] font-semibold text-foreground">Downloads</h3>
            <span class="text-[13px] text-foreground-muted tabular-nums">
              {{ metrics?.used_human ?? '0 B' }} of {{ metrics?.max_human ?? '0 B' }}
            </span>
          </div>
          <div class="mt-3 h-1.5 bg-black/[0.06] rounded-full overflow-hidden">
            <div
              class="h-full rounded-full transition-[width] duration-700 ease-spring"
              :class="usedPct > 90 ? 'bg-danger' : usedPct > 70 ? 'bg-warning' : 'bg-foreground/70'"
              :style="{ width: `${Math.min(usedPct, 100)}%` }"
            />
          </div>
          <div class="mt-2 flex items-center justify-between text-[12px] text-foreground-muted tabular-nums">
            <span>{{ items.length }} items · {{ activeCount }} active</span>
            <span v-if="refreshing" class="spinner w-3 h-3 text-foreground-muted/60" />
          </div>
        </div>

        <!-- List -->
        <div class="flex-1 overflow-y-auto min-h-0 px-2 pb-2 border-t border-black/[0.05]">
          <div v-if="loading" class="p-3 space-y-3">
            <Skeleton v-for="n in 3" :key="n" class="h-20 w-full !rounded-2xl" />
          </div>

          <div v-else-if="enrichedItems.length === 0" class="py-14 text-center">
            <p class="text-[15px] font-medium text-foreground">Nothing cached</p>
            <p class="mt-1 text-[13px] text-foreground-muted">Titles you play are downloaded on demand.</p>
          </div>

          <div
            v-for="item in enrichedItems"
            v-else
            :key="item.hash"
            class="group/item px-3 py-3 mt-1 rounded-2xl hover:bg-black/[0.03] transition-colors"
          >
            <div class="flex items-center gap-2">
              <p class="text-[15px] font-semibold text-foreground truncate min-w-0">{{ item.displayCode }}</p>
              <span v-if="item.quality === 'HD'" class="chip bg-black/[0.06] text-foreground">HD</span>
              <span class="ml-auto shrink-0 flex items-center gap-1.5 text-[12px] font-medium" :class="stateTextClass(item)">
                <span class="w-1.5 h-1.5 rounded-full bg-current" :class="{ 'animate-pulse': item.state === 'downloading' || item.state?.includes('checking') }" />
                {{ stateLabel(item) }}
              </span>
            </div>

            <!-- Piece map -->
            <div class="mt-2.5 flex h-1.5 rounded-full overflow-hidden bg-black/[0.06]">
              <div
                v-for="(seg, idx) in item.piece_segments"
                :key="idx"
                class="h-full"
                :style="{ width: `${100 / item.piece_segments.length}%`, backgroundColor: laneColor(seg[2]) }"
                :title="`${seg[0].toFixed(0)}–${seg[1].toFixed(0)}%: ${laneLabel(seg[2])}`"
              />
            </div>

            <div class="mt-2 flex items-center flex-wrap gap-x-2 gap-y-1 text-[12px] text-foreground-muted tabular-nums whitespace-nowrap">
              <span>{{ formatSize(item.local_size) }} / {{ formatSize(item.video_size) }}</span>
              <span class="text-foreground-muted/40">·</span>
              <span>{{ tierLabel(item) }}</span>
              <template v-if="item.peers > 0">
                <span class="text-foreground-muted/40">·</span>
                <span>{{ item.peers }} peers</span>
              </template>
              <span v-if="item.download_rate > 0" class="text-foreground">↓ {{ formatSpeed(item.download_rate) }}</span>
              <span v-if="item.verified_pieces > 0 && item.state?.includes('checking')" class="text-warning">
                {{ item.verified_pieces }} verified
              </span>

              <span class="ml-auto flex items-center gap-1 shrink-0 sm:opacity-0 sm:group-hover/item:opacity-100 transition-opacity">
                <button
                  v-if="!item.head_ready && item.progress < 99.9"
                  class="h-7 px-2.5 rounded-full text-[12px] font-medium text-foreground hover:bg-black/[0.06] active:scale-[0.96] transition"
                  @click="boostItem(item.hash)"
                >
                  Boost
                </button>
                <button
                  class="h-7 px-2.5 rounded-full text-[12px] font-medium text-danger hover:bg-danger/10 active:scale-[0.96] transition"
                  @click="removeItem(item.hash)"
                >
                  Remove
                </button>
              </span>
            </div>
          </div>
        </div>

        <!-- Footer -->
        <div class="px-5 py-3 border-t border-black/[0.05] flex items-center justify-between gap-3">
          <div class="hidden sm:flex items-center gap-3 text-[11px] text-foreground-muted whitespace-nowrap">
            <span class="flex items-center gap-1"><span class="w-1.5 h-1.5 rounded-full" :style="{ background: laneColor(2) }" />Cached</span>
            <span class="flex items-center gap-1"><span class="w-1.5 h-1.5 rounded-full" :style="{ background: laneColor(1) }" />Downloading</span>
            <span class="flex items-center gap-1"><span class="w-1.5 h-1.5 rounded-full" :style="{ background: laneColor(3) }" />Corrupt</span>
          </div>
          <div class="flex items-center gap-1 ml-auto whitespace-nowrap">
            <button class="h-8 px-3 rounded-full text-[13px] font-medium text-foreground hover:bg-black/[0.05] active:scale-[0.96] transition" @click="refresh(true)">
              Refresh
            </button>
            <button
              class="h-8 px-3 rounded-full text-[13px] font-medium text-danger hover:bg-danger/10 active:scale-[0.96] transition disabled:opacity-35"
              :disabled="items.length === 0"
              @click="clearAll"
            >
              Clear All
            </button>
          </div>
        </div>
      </div>
    </Transition>
  </div>
</template>

<script setup lang="ts">
import type { CacheMetrics, Star } from '~/types/api'

const props = defineProps<{
  stars?: Star[]
}>()

const isOpen = ref(false)
const rootRef = ref<HTMLElement | null>(null)
useDismiss(rootRef, isOpen)
const items = ref<any[]>([])
const metrics = ref<CacheMetrics | null>(null)
const loading = ref(false)
const refreshing = ref(false)
let unsubs: (() => void)[] = []
let refreshDebounceTimer: ReturnType<typeof setTimeout> | null = null

const { getCacheItems, getCacheMetrics, deleteCache, addTorrent } = useApi()

const WORK_CODE_RE = /[A-Z]{2,6}-\d{3,5}/i
function extractCode(name?: string): string | null {
  if (!name) return null
  const m = name.match(WORK_CODE_RE)
  return m ? m[0].toUpperCase() : null
}

const hashToInfo = computed(() => {
  const map: Record<string, { code: string; number: number }> = {}
  for (const star of (props.stars || [])) {
    for (const t of (star.titles || [])) {
      if (t.magnet) {
        const match = t.magnet.match(/xt=urn:btih:([a-f0-9]{40})/i)
        if (match) {
          const hash = match[1].toLowerCase()
          if (!map[hash]) {
            map[hash] = { code: t.code, number: t.number || 0 }
          }
        }
      }
    }
  }
  return map
})

const enrichedItems = computed(() => {
  const list = items.value.map(item => {
    const info = hashToInfo.value[item.hash]
    const code = item.work_code
      || info?.code
      || extractCode(item.video_file)
      || extractCode(item.name)
      || ''
    return {
      ...item,
      code,
      number: info?.number || 0,
      displayCode: code || item.name || item.hash.slice(0, 12),
    }
  })
  return list.sort((a, b) => {
    if (a.number && b.number) return a.number - b.number
    if (a.number) return -1
    if (b.number) return 1
    return 0
  })
})

const activeCount = computed(() => items.value.filter(i => i.progress > 0 && i.progress < 99.9).length)

const usedPct = computed(() => {
  const used = metrics.value?.used_bytes || 0
  const max = metrics.value?.max_bytes || 0
  return max > 0 ? (used / max) * 100 : 0
})

function formatSize(bytes: number): string {
  if (!bytes) return '0 B'
  if (bytes > 1024 * 1024 * 1024) return `${(bytes / 1024 / 1024 / 1024).toFixed(1)} GB`
  if (bytes > 1024 * 1024) return `${(bytes / 1024 / 1024).toFixed(0)} MB`
  if (bytes > 1024) return `${(bytes / 1024).toFixed(0)} KB`
  return `${bytes} B`
}

function formatSpeed(rate: number): string {
  if (rate > 1024 * 1024) return `${(rate / 1024 / 1024).toFixed(1)} MB/s`
  if (rate > 1024) return `${(rate / 1024).toFixed(1)} KB/s`
  return `${rate} B/s`
}

// libtorrent reports finished/seeding once every *wanted* piece is in, and
// on-demand priorities leave most pieces unwanted. Completeness comes from
// disk-verified progress only.
function isPartial(item: any): boolean {
  return (item.state === 'finished' || item.state === 'seeding') && item.progress < 99.9
}

function stateTextClass(item: any): string {
  if (isPartial(item)) return 'text-foreground-muted'
  if (item.state === 'finished' || item.state === 'seeding') return 'text-success'
  if (item.state?.includes('checking')) return 'text-warning'
  if (item.state === 'downloading') return 'text-info'
  return 'text-foreground-muted'
}

function stateLabel(item: any): string {
  if (isPartial(item)) {
    if (item.progress <= 0) return 'Idle'
    return `Partial ${item.progress < 1 ? '<1' : Math.floor(item.progress)}%`
  }
  const map: Record<string, string> = {
    checking_files: 'Verifying',
    checking_resume_data: 'Verifying',
    downloading_metadata: 'Metadata',
    downloading: 'Downloading',
    finished: 'Finished',
    seeding: 'Seeding',
    allocating: 'Allocating',
  }
  return map[item.state] || item.state || 'Waiting'
}

function tierLabel(item: any): string {
  const map: Record<string, string> = {
    hot: 'Hot',
    warm: 'Warm',
    seed: 'Cold',
    fragment: 'Fragment',
  }
  return map[item.tier] || item.tier || '-'
}

function laneColor(state: number): string {
  // Missing is transparent so the track shows through, as in the player.
  const colors: Record<number, string> = {
    0: 'transparent',
    1: '#FF9F0A',
    2: 'rgba(29,29,31,0.72)',
    3: '#FF453A',
  }
  return colors[state] || 'transparent'
}

function laneLabel(state: number): string {
  const labels: Record<number, string> = {
    0: 'Missing',
    1: 'Downloading',
    2: 'Cached',
    3: 'Corrupt',
  }
  return labels[state] || 'Unknown'
}

async function refresh(showLoading = false) {
  if (refreshing.value) return
  if (showLoading && items.value.length === 0) loading.value = true
  refreshing.value = true
  try {
    const cacheData = await getCacheItems() as any
    items.value = cacheData.items || []
    metrics.value = await getCacheMetrics() as CacheMetrics
  } catch (e) {
    console.error('refresh cache failed:', e)
  } finally {
    loading.value = false
    refreshing.value = false
  }
}

function scheduleRefresh() {
  if (refreshDebounceTimer) clearTimeout(refreshDebounceTimer)
  refreshDebounceTimer = setTimeout(() => refresh(false), 400)
}

async function removeItem(hash: string) {
  try {
    await deleteCache(hash)
    await refresh(false)
  } catch (e) {
    console.error('delete cache failed:', e)
  }
}

async function boostItem(hash: string) {
  const item = items.value.find(i => i.hash === hash)
  if (!item?.magnet) return
  try {
    await addTorrent(item.magnet)
  } catch {
    // ignore
  }
}

async function clearAll() {
  if (!confirm('Clear all cache items?')) return
  loading.value = true
  try {
    await Promise.all(items.value.map(async (item) => {
      try {
        await deleteCache(item.hash)
      } catch {
        // ignore
      }
    }))
  } finally {
    loading.value = false
    await refresh(false)
  }
}

watch(isOpen, (open) => {
  if (open) {
    refresh(true)
    const { onServerEvent } = useEventSource()
    unsubs = [
      onServerEvent('cache.update', () => {
        scheduleRefresh()
      }),
      // Field-level live update for visible rows — no refetch, no list re-sort.
      onServerEvent('torrent.progress', (data: any) => {
        const item = items.value.find((i) => i.hash === data.hash)
        if (!item) return
        Object.assign(item, {
          state: data.state,
          progress: data.progress,
          download_rate: data.download_rate,
          upload_rate: data.upload_rate,
          peers: data.peers,
          head_ready: data.head_ready,
          verified_pieces: data.verified_pieces,
        })
      }),
      // Server coalesced our event queue — refetch once.
      onServerEvent('sync.resync_required', () => {
        refresh(false)
      }),
    ]
  } else {
    unsubs.forEach((fn) => fn())
    unsubs = []
    if (refreshDebounceTimer) {
      clearTimeout(refreshDebounceTimer)
      refreshDebounceTimer = null
    }
  }
})

onUnmounted(() => {
  unsubs.forEach((fn) => fn())
  unsubs = []
  if (refreshDebounceTimer) clearTimeout(refreshDebounceTimer)
})
</script>

