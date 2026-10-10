<template>
  <section :id="id" class="group/star">
    <!-- Section header: name sits on the page, the shelf below is one surface -->
    <div class="flex items-end justify-between gap-4 mb-4 sm:mb-5 px-1">
      <div class="min-w-0">
        <h2 class="text-[26px] sm:text-[32px] font-bold text-foreground leading-tight truncate">
          {{ star.name }}
        </h2>
        <p class="mt-0.5 text-[14px] text-foreground-muted tabular-nums">
          {{ star.titles?.length ?? 0 }} titles<span v-if="star.number"> · No. {{ star.number }}</span>
        </p>
      </div>
      <button
        class="btn-icon text-foreground-muted hover:text-danger hover:bg-danger/10 sm:opacity-0 sm:group-hover/star:opacity-100 focus-visible:opacity-100"
        title="Unfollow star"
        aria-label="Unfollow star"
        :disabled="deleting"
        @click="onDelete"
      >
        <svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
          <polyline points="3 6 5 6 21 6" />
          <path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2" />
        </svg>
      </button>
    </div>

    <div class="surface overflow-hidden">
      <!-- Hero -->
      <div v-if="activeTitle" class="flex flex-col sm:flex-row gap-5 sm:gap-8 p-4 sm:p-6">
        <div class="w-full sm:w-[300px] md:w-[360px] lg:w-[440px] shrink-0 rounded-[18px] overflow-hidden bg-fill">
          <img
            v-if="activeTitle.cover_url && !activeImgError"
            ref="heroImg"
            :key="activeTitle.code"
            :src="activeTitle.cover_url"
            :srcset="heroSrcset(activeTitle)"
            sizes="(min-width: 1024px) 440px, (min-width: 768px) 360px, (min-width: 640px) 300px, calc(100vw - 32px)"
            :alt="activeTitle.code"
            class="w-full h-auto block transition-opacity duration-500 ease-spring"
            :class="heroLoaded ? 'opacity-100' : 'opacity-0'"
            :style="{ aspectRatio: coverAR(activeTitle) }"
            loading="lazy"
            decoding="async"
            @load="heroLoaded = true"
            @error="activeImgError = true"
          />
          <div
            v-else
            class="flex flex-col items-center justify-center p-6 text-center"
            :style="{ aspectRatio: coverAR(activeTitle) }"
          >
            <span class="text-[19px] font-semibold text-foreground/50">{{ activeTitle.code }}</span>
            <span class="mt-1.5 text-[14px] text-foreground-muted/70 line-clamp-3">{{ activeTitle.title }}</span>
          </div>
        </div>

        <Transition name="swap" mode="out-in">
          <div :key="activeTitle.code" class="flex-1 min-w-0 flex flex-col justify-center sm:py-2">
            <div class="flex items-center flex-wrap gap-x-2 gap-y-1 text-[13px] font-medium text-foreground-muted tabular-nums">
              <span>#{{ activeTitle.number || activeIndex + 1 }}</span>
              <template v-if="activeTitle.date">
                <span class="text-foreground-muted/40">·</span>
                <span>{{ fmtDate(activeTitle.date) }}</span>
              </template>
              <span v-if="activeIsHd" class="chip bg-black/[0.06] text-foreground">HD</span>
              <span v-if="activeTitle.magnet_status === 'dead'" class="chip bg-danger/10 text-danger">Unavailable</span>
            </div>
            <h3 class="mt-2 text-[30px] sm:text-[40px] font-bold text-foreground leading-[1.05]">
              {{ activeTitle.code }}
            </h3>
            <p class="mt-3 text-[15px] sm:text-[17px] text-foreground-muted leading-relaxed line-clamp-3">
              {{ activeTitle.title }}
            </p>

            <!-- Copy is the real primary action: 49 copies vs 1 in-browser
                 play in the first two weeks of tracking -->
            <div class="flex items-center gap-2.5 mt-6 sm:mt-7">
              <button
                class="btn flex-1 sm:flex-none sm:px-6"
                :class="copied ? 'btn-success' : 'btn-primary'"
                :disabled="!activePlayable"
                @click="copyMagnet"
              >
                <svg v-if="!copied" width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round">
                  <rect x="9" y="9" width="13" height="13" rx="2" />
                  <path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1" />
                </svg>
                <svg v-else width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round" stroke-linejoin="round">
                  <polyline points="20 6 9 17 4 12" />
                </svg>
                {{ copied ? 'Copied' : 'Copy Magnet' }}
              </button>

              <button class="btn btn-secondary flex-1 sm:flex-none sm:px-6" :disabled="!activePlayable" @click="onPlay">
                <svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor"><path d="M7 4.5v15l12.5-7.5z" /></svg>
                Play
              </button>

              <button
                class="btn-icon w-11 h-11"
                :class="activeLiked ? 'bg-accent/10 text-accent hover:bg-accent/15' : 'bg-black/[0.05] hover:bg-black/[0.08]'"
                :aria-pressed="activeLiked"
                :aria-label="activeLiked ? 'Unlike' : 'Like'"
                :disabled="liking"
                @click="toggleLike"
              >
                <svg
                  width="18" height="18" viewBox="0 0 24 24"
                  :fill="activeLiked ? 'currentColor' : 'none'"
                  stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"
                  class="transition-transform duration-300 ease-spring"
                  :class="activeLiked ? 'scale-110' : 'scale-100'"
                >
                  <path d="M20.84 4.61a5.5 5.5 0 0 0-7.78 0L12 5.67l-1.06-1.06a5.5 5.5 0 0 0-7.78 7.78l1.06 1.06L12 21.23l7.78-7.78 1.06-1.06a5.5 5.5 0 0 0 0-7.78z" />
                </svg>
              </button>
            </div>
          </div>
        </Transition>
      </div>

      <!-- Thumbnail rail -->
      <div class="border-t border-black/[0.05]">
        <div
          ref="rowRef"
          class="flex gap-3 sm:gap-4 items-start overflow-x-auto scrollbar-hide px-4 sm:px-6 py-4 sm:py-5 snap-x snap-mandatory scroll-px-4 sm:scroll-px-6"
          @scroll.passive="onRowScroll"
        >
          <!-- Windowed rendering: spacers keep the scroll width exact while
               only the visible ±THUMB_BUFFER thumbnails exist in the DOM -->
          <div v-if="leadPad > 0" class="shrink-0 h-px" :style="{ width: `${leadPad}px` }" />
          <button
            v-for="{ title, idx } in windowedTitles"
            :key="title.code"
            class="group/thumb relative shrink-0 w-[112px] sm:w-[144px] md:w-[168px] rounded-xl overflow-hidden bg-fill snap-start transition-[opacity,transform,box-shadow] duration-300 ease-spring active:scale-[0.96] active:duration-100"
            :class="[
              activeIndex === idx
                ? 'ring-2 ring-accent ring-offset-2 ring-offset-white'
                : 'opacity-[0.72] hover:opacity-100',
              title.magnet_status === 'dead' ? 'grayscale !opacity-40' : '',
            ]"
            :aria-label="title.code"
            :aria-current="activeIndex === idx"
            @click="activeIndex = idx"
          >
            <!-- One-click magnet copy: the real primary workflow -->
            <span
              v-if="title.magnet"
              role="button"
              tabindex="-1"
              class="absolute top-1.5 right-1.5 z-10 w-7 h-7 rounded-full bg-black/55 backdrop-blur-md text-white flex items-center justify-center opacity-0 scale-90 group-hover/thumb:opacity-100 group-hover/thumb:scale-100 transition duration-200 ease-spring hover:bg-accent"
              :class="{ '!opacity-100 !scale-100 !bg-success': copiedCode === title.code }"
              title="Copy magnet"
              @click.stop="copyTitleMagnet(title)"
            >
              <svg v-if="copiedCode !== title.code" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2">
                <rect x="9" y="9" width="13" height="13" rx="2" />
                <path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1" />
              </svg>
              <svg v-else width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3">
                <polyline points="20 6 9 17 4 12" />
              </svg>
            </span>
            <img
              v-if="title.cover_url && !thumbErrors[title.code]"
              :src="title.cover_thumb_url || `/api/cover/${title.code}?thumb=1`"
              :alt="title.code"
              class="w-full h-auto block"
              :style="{ aspectRatio: coverAR(title) }"
              decoding="async"
              @error="thumbErrors[title.code] = true"
            />
            <div
              v-else
              class="flex items-center justify-center p-2 text-center"
              :style="{ aspectRatio: coverAR(title) }"
            >
              <span class="text-[11px] font-semibold text-foreground/50">{{ title.code }}</span>
            </div>
            <span class="absolute bottom-1.5 left-1.5 chip !px-1.5 bg-black/55 backdrop-blur-md text-white text-[10px] tabular-nums">
              {{ title.number || idx + 1 }}
            </span>
          </button>
          <div v-if="trailPad > 0" class="shrink-0 h-px" :style="{ width: `${trailPad}px` }" />
        </div>
      </div>
    </div>
  </section>
</template>

<script setup lang="ts">
import type { Star, Title } from '~/types/api'

const props = defineProps<{
  star: Star
  index?: number
}>()

const emit = defineEmits<{
  (e: 'play', magnet: string, code: string, starCode: string): void
  (e: 'deleted', code: string): void
}>()

const { track } = useTrack()
const { add: addLog } = useEventLog()

const id = computed(() => props.star.code.toLowerCase())
const activeIndex = ref(0)
const activeTitle = computed(() => props.star.titles?.[activeIndex.value] || null)

const activeImgError = ref(false)
const thumbErrors = ref<Record<string, boolean>>({})

// Hero fades in once decoded instead of painting top-to-bottom. A cached
// image can finish before the listener runs, so also trust `complete`.
const heroImg = ref<HTMLImageElement | null>(null)
const heroLoaded = ref(false)
watch(heroImg, (img) => {
  if (img?.complete && img.naturalWidth > 0) heroLoaded.value = true
}, { flush: 'post' })

const activeIsHd = computed(() => {
  const t = activeTitle.value
  if (!t || t.magnet_status === 'dead') return false
  const res = t.resolution?.toLowerCase() ?? ''
  return res.includes('1080') || res.includes('4k')
})

// Reserve each cover's box at its true aspect ratio so the layout never
// jumps when bytes arrive. Fallback 3/2: virtually all covers are
// ~800x537 landscape jackets, not 2:3 portraits.
function coverAR(t: Title): string {
  return t.cover_w && t.cover_h ? `${t.cover_w} / ${t.cover_h}` : '3 / 2'
}

// Hero srcset: let the browser pick the smallest variant that covers the
// display box (440px max, ≤2x DPR → the 800px mid wins almost everywhere).
// Decoding a 1600-2200px original for a 440px box was the main render stall.
function heroSrcset(t: Title): string | undefined {
  const candidates: string[] = []
  if (t.cover_thumb_url) candidates.push(`${t.cover_thumb_url} 400w`)
  if (t.cover_mid_url) candidates.push(`${t.cover_mid_url} 800w`)
  if (t.cover_url && t.cover_url.startsWith('/images/')) {
    candidates.push(`${t.cover_url} ${t.cover_w || 1600}w`)
  }
  return candidates.length > 1 ? candidates.join(', ') : undefined
}

// ── Thumbnail row windowing ──────────────────────────────────────────
// A star can have ~100 titles; mounting every button+img keeps thousands of
// DOM nodes alive after a full-catalog scroll. Render only the visible
// window (±THUMB_BUFFER) and pad with spacers so the scroll width (and snap
// positions) stay exactly as if every item were present.
const THUMB_BUFFER = 8
const rowRef = ref<HTMLElement | null>(null)
const rowScrollLeft = ref(0)
const rowViewWidth = ref(0)
const thumbItemWidth = ref(0)
const thumbGap = ref(0)
const thumbStride = computed(() => thumbItemWidth.value + thumbGap.value)

const thumbRange = computed(() => {
  const total = props.star.titles?.length ?? 0
  if (!thumbStride.value || !rowViewWidth.value) {
    // SSR / pre-measure: render a small head window only
    return { start: 0, end: Math.min(total, 20) }
  }
  const firstVisible = Math.floor(rowScrollLeft.value / thumbStride.value)
  const visible = Math.ceil(rowViewWidth.value / thumbStride.value)
  const start = Math.max(0, firstVisible - THUMB_BUFFER)
  const end = Math.min(total, firstVisible + visible + THUMB_BUFFER)
  return { start, end }
})

const windowedTitles = computed(() => {
  const titles = props.star.titles ?? []
  const { start, end } = thumbRange.value
  return titles.slice(start, end).map((title, i) => ({ title, idx: start + i }))
})

// Spacer widths must reproduce the flex layout exactly: N hidden items occupy
// N*width + (N-1)*gap; the spacer itself adds one more gap back.
const leadPad = computed(() => {
  const { start } = thumbRange.value
  return start > 0 ? start * thumbStride.value - thumbGap.value : 0
})
const trailPad = computed(() => {
  const total = props.star.titles?.length ?? 0
  const remaining = total - thumbRange.value.end
  return remaining > 0 ? remaining * thumbStride.value - thumbGap.value : 0
})

function onRowScroll() {
  rowScrollLeft.value = rowRef.value?.scrollLeft ?? 0
}

let rowResizeObserver: ResizeObserver | null = null

function measureRow() {
  const row = rowRef.value
  if (!row) return
  rowViewWidth.value = row.clientWidth
  rowScrollLeft.value = row.scrollLeft
  const firstBtn = row.querySelector('button')
  if (firstBtn) {
    thumbItemWidth.value = (firstBtn as HTMLElement).offsetWidth
    thumbGap.value = parseFloat(getComputedStyle(row).columnGap) || 0
  }
}

onMounted(() => {
  measureRow()
  if (rowRef.value) {
    rowResizeObserver = new ResizeObserver(measureRow)
    rowResizeObserver.observe(rowRef.value)
  }
})

onUnmounted(() => {
  rowResizeObserver?.disconnect()
})
const copied = ref(false)
const liking = ref(false)
const activeLiked = computed(() => activeTitle.value?.user_liked ?? false)
const activePlayable = computed(() =>
  !!activeTitle.value?.magnet && activeTitle.value?.magnet_status !== 'dead'
)

watch(() => props.star.titles, (titles, prev) => {
  // Full-catalog refetches (sync.completed / star.ready / resync) replace
  // the titles array; keep the user's picked thumbnail if it still exists
  // instead of snapping every row back to #1 and reloading the hero image.
  const current = prev?.[activeIndex.value]?.code
  const kept = current ? titles?.findIndex(t => t.code === current) : -1
  activeIndex.value = kept != null && kept >= 0 ? kept : 0
  activeImgError.value = false
})

watch(activeIndex, () => {
  activeImgError.value = false
})

// Keyed on the code, not the index: a refetch can shift the kept title's
// index without remounting its <img>, and would leave it invisible.
watch(() => activeTitle.value?.code, () => {
  heroLoaded.value = false
})

function onPlay() {
  if (!activePlayable.value) return
  track('play', { code: activeTitle.value.code, star_code: props.star.code })
  addLog({ kind: 'action', title: `Play ${activeTitle.value.code}`, detail: props.star.name, state: 'info' })
  emit('play', activeTitle.value.magnet!, activeTitle.value.code, props.star.code)
}

async function toggleLike() {
  if (liking.value || !activeTitle.value) return
  liking.value = true
  try {
    const { likeTitle } = useApi()
    const newVal = !activeLiked.value
    await likeTitle(activeTitle.value.code, newVal)
    activeTitle.value.user_liked = newVal
    track(newVal ? 'like' : 'unlike', { code: activeTitle.value.code, star_code: props.star.code })
    addLog({ kind: 'action', title: `${newVal ? 'Liked' : 'Unliked'} ${activeTitle.value.code}`, detail: props.star.name, state: 'success' })
  } catch (e: any) {
    console.error('like failed:', e)
    addLog({ kind: 'action', title: `Like failed: ${activeTitle.value?.code}`, detail: String(e?.message ?? e), state: 'error' })
  } finally {
    liking.value = false
  }
}

function copyMagnet() {
  const magnet = activeTitle.value?.magnet
  if (!magnet) return
  navigator.clipboard.writeText(magnet).then(() => {
    copied.value = true
    setTimeout(() => copied.value = false, 1500)
    track('copy_magnet', { code: activeTitle.value?.code, star_code: props.star.code, meta: { source: 'hero' } })
  }).catch(() => {
    // ignore
  })
}

const copiedCode = ref('')

function copyTitleMagnet(title: Title) {
  if (!title.magnet) return
  navigator.clipboard.writeText(title.magnet).then(() => {
    copiedCode.value = title.code
    setTimeout(() => {
      if (copiedCode.value === title.code) copiedCode.value = ''
    }, 1500)
    track('copy_magnet', { code: title.code, star_code: props.star.code, meta: { source: 'thumbnail' } })
  }).catch(() => {
    // ignore
  })
}

const deleting = ref(false)

async function onDelete() {
  if (!confirm(`Delete star "${props.star.name}" and all associated title data?\n(Cache files will be preserved)`)) {
    return
  }
  deleting.value = true
  try {
    const { deleteStar } = useApi()
    await deleteStar(props.star.code)
    emit('deleted', props.star.code)
  } catch (e: any) {
    alert(e?.message || 'Delete failed')
  } finally {
    deleting.value = false
  }
}

function fmtDate(dateStr?: string): string {
  if (!dateStr) return ''
  const parts = dateStr.split('/')
  if (parts.length === 3) {
    return `${parts[2]}-${parts[1].padStart(2, '0')}-${parts[0].padStart(2, '0')}`
  }
  return dateStr
}
</script>
