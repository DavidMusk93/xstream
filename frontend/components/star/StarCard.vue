<template>
  <section :id="id" class="group/star">
    <!-- Section header: name sits on the page, the shelf below is one surface -->
    <div v-reveal class="flex items-end justify-between gap-4 mb-4 sm:mb-5 px-1">
      <div class="min-w-0">
        <p class="eyebrow">
          <span class="text-accent">{{ String((index ?? 0) + 1).padStart(2, '0') }}</span>
          <span class="tabular-nums">{{ star.titles?.length ?? 0 }} titles</span>
          <a
            v-if="star.x?.handle && !star.x.posts?.length"
            :href="`https://x.com/${star.x.handle}`"
            target="_blank"
            rel="noopener noreferrer"
            class="hover:text-foreground transition-colors"
          >@{{ star.x.handle }}</a>
          <span class="h-px w-10 bg-black/10" />
        </p>
        <h2 class="mt-2 text-[28px] sm:text-[36px] font-bold text-foreground leading-[1.1] truncate">
          {{ star.name }}
        </h2>
      </div>
      <div class="flex items-center gap-1 shrink-0">
        <button
          class="btn-icon text-foreground-muted hover:text-foreground sm:opacity-0 sm:group-hover/star:opacity-100 focus-visible:opacity-100"
          :title="`X posts for ${star.name}`"
          :aria-label="`X posts for ${star.name}`"
          @click="emit('social', star.code)"
        >
          <XGlyph class="w-[15px] h-[15px]" />
        </button>
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
    </div>

    <div v-reveal="0.08">
      <!-- Stage: the cover is the protagonist; info reads like a caption -->
      <div v-if="activeTitle" class="grid gap-6 sm:gap-8 lg:grid-cols-[minmax(0,1.65fr)_minmax(0,1fr)] lg:gap-12">
        <div
          ref="heroStageRef"
          class="hero-stage group/hero relative w-full max-w-[760px] rounded-[22px] overflow-hidden bg-fill shadow-[0_30px_60px_-34px_rgba(0,0,0,0.5)] touch-pan-y select-none outline-none"
          :class="{ 'controls-shown': controlsShown }"
          tabindex="0"
          role="group"
          :aria-label="`${activeTitle.code} cover, swipe or use arrow keys to browse titles`"
          @pointerdown="onPointerDown"
          @pointermove="(e) => onPointerMove(e, clampDrag)"
          @pointerup="onPointerUp"
          @pointercancel="onPointerCancel"
          @wheel="onWheel"
          @keydown="onKeydown"
        >
          <div
            class="hero-frame relative w-full bg-fill overflow-hidden"
            :style="{ aspectRatio: coverAR(activeTitle) }"
          >
            <img
              v-if="heroLqipSrc(activeTitle) && !heroLoaded && !activeImgError"
              :key="`lqip-${activeTitle.code}`"
              :src="heroLqipSrc(activeTitle)!"
              alt=""
              aria-hidden="true"
              decoding="async"
              draggable="false"
              class="hero-lqip absolute inset-0 w-full h-full object-contain pointer-events-none"
              :style="{
                transform: dragX ? `translate3d(${dragX}px,0,0)` : undefined,
              }"
            />
            <Transition name="hero-crossfade">
              <img
                v-if="activeTitle.cover_url && !activeImgError"
                ref="heroImg"
                :key="activeTitle.code"
                :src="heroSrc(activeTitle)"
                :srcset="heroSrcset(activeTitle)"
                sizes="(min-width: 1280px) 740px, (min-width: 1024px) 60vw, (min-width: 808px) 760px, calc(100vw - 32px)"
                :alt="activeTitle.code"
                fetchpriority="high"
                loading="eager"
                decoding="async"
                draggable="false"
                class="hero-hi absolute inset-0 w-full h-full object-contain block [transition-timing-function:var(--ease-out)]"
                :class="[
                  heroLoaded ? 'opacity-100' : 'opacity-0',
                  dragging ? 'duration-0 will-change-transform' : 'transition-opacity duration-150',
                  !dragX && !dragging ? 'sm:group-hover/hero:scale-[1.015]' : '',
                ]"
                :style="{
                  transform: dragX ? `translate3d(${dragX}px,0,0)` : undefined,
                }"
                @load="onHeroImgLoad"
                @error="activeImgError = true"
              />
              <div
                v-else
                :key="`${activeTitle.code}-ph`"
                class="absolute inset-0 flex flex-col items-center justify-center p-6 text-center"
              >
                <span class="text-[19px] font-semibold text-foreground/50">{{ activeTitle.code }}</span>
                <span class="mt-1.5 text-[14px] text-foreground-muted/70 line-clamp-3">{{ activeTitle.title }}</span>
              </div>
            </Transition>
          </div>

          <!-- Stepping lives on the cover itself: revealed by hover / focus
               on desktop, briefly by a swipe on touch -->
          <template v-if="total > 1">
            <button
              class="hero-nav left-3 sm:left-4"
              :class="{ 'is-off': activeIndex <= 0 }"
              aria-label="Previous title"
              :disabled="activeIndex <= 0"
              @click="step(-1)"
            >
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"><polyline points="15 18 9 12 15 6" /></svg>
            </button>
            <button
              class="hero-nav right-3 sm:right-4"
              :class="{ 'is-off': activeIndex >= total - 1 }"
              aria-label="Next title"
              :disabled="activeIndex >= total - 1"
              @click="step(1)"
            >
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"><polyline points="9 18 15 12 9 6" /></svg>
            </button>
            <span class="hero-count font-mono">{{ activeIndex + 1 }} / {{ total }}</span>
          </template>
        </div>

        <div class="min-w-0 flex flex-col lg:py-1 lg:pb-2">
          <Transition name="swap">
            <div :key="activeTitle.code" class="lg:mt-auto">
              <div class="flex items-center flex-wrap gap-x-2 gap-y-1 text-[13px] font-medium text-foreground-muted tabular-nums">
                <span v-if="activeTitle.date">{{ fmtDate(activeTitle.date) }}</span>
                <span v-if="activeIsHd" class="chip bg-black/[0.06] text-foreground">HD</span>
                <span v-if="activeTitle.magnet_status === 'dead'" class="chip bg-danger/10 text-danger">Unavailable</span>
              </div>
              <h3 class="mt-2 text-[34px] sm:text-[48px] lg:text-[56px] font-bold text-foreground leading-[1] tracking-[-0.03em]">
                {{ activeTitle.code }}
              </h3>
              <p class="mt-4 text-[15px] sm:text-[17px] text-foreground-muted leading-relaxed line-clamp-3 lg:line-clamp-4">
                {{ activeTitle.title }}
              </p>

              <!-- Icon-only actions; Copy stays first and accent — it is the
                   real primary action (49 copies vs 1 play in early tracking) -->
              <div class="flex items-center gap-3 mt-6 sm:mt-8">
                <button
                  class="action text-white shadow-[0_6px_20px_-6px_rgba(255,55,95,0.6)] hover:-translate-y-0.5"
                  :class="copied ? 'bg-success shadow-none' : 'bg-accent hover:bg-accent-hover'"
                  :data-tip="copied ? 'Copied' : 'Copy magnet'"
                  :data-tip-show="copied || undefined"
                  aria-label="Copy magnet"
                  :disabled="!activePlayable"
                  @click="copyMagnet"
                >
                  <Transition name="icon-swap" mode="out-in">
                    <MagnetIcon v-if="!copied" key="copy" />
                    <svg v-else key="done" width="19" height="19" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.8" stroke-linecap="round" stroke-linejoin="round">
                      <polyline points="20 6 9 17 4 12" />
                    </svg>
                  </Transition>
                </button>

                <button
                  class="action bg-foreground text-white hover:bg-black hover:-translate-y-0.5"
                  data-tip="Play"
                  aria-label="Play"
                  :disabled="!activePlayable"
                  @click="onPlay"
                >
                  <svg width="17" height="17" viewBox="0 0 24 24" fill="currentColor" class="ml-0.5"><path d="M7 4.5v15l12.5-7.5z" /></svg>
                </button>

                <button
                  class="action hover:-translate-y-0.5"
                  :class="activeLiked ? 'bg-accent/10 text-accent hover:bg-accent/15' : 'bg-black/[0.05] text-foreground hover:bg-black/[0.08]'"
                  :data-tip="activeLiked ? 'Liked' : 'Like'"
                  :aria-pressed="activeLiked"
                  :aria-label="activeLiked ? 'Unlike' : 'Like'"
                  :disabled="liking"
                  @click="toggleLike"
                >
                  <svg
                    width="19" height="19" viewBox="0 0 24 24"
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
      </div>

      <!-- Gallery: every title gets a captioned card -->
      <div
        ref="rowRef"
        class="group/rail mt-8 sm:mt-10 flex gap-4 sm:gap-5 items-start overflow-x-auto scrollbar-hide pt-1 pb-2 snap-x snap-mandatory fade-edge-r"
        @scroll.passive="onRowScroll"
      >
        <!-- Windowed rendering: spacers keep the scroll width exact while
             only the visible ±THUMB_BUFFER thumbnails exist in the DOM -->
        <div v-if="leadPad > 0" class="shrink-0 h-px" :style="{ width: `${leadPad}px` }" />
        <button
          v-for="{ title, idx } in windowedTitles"
          :key="title.code"
          class="group/thumb shrink-0 w-[148px] sm:w-[188px] lg:w-[212px] text-left snap-start transition-transform duration-300 active:scale-[0.97] active:duration-100 [transition-timing-function:var(--ease-out)]"
          :class="activeIndex === idx ? '' : 'sm:hover:-translate-y-1'"
          :aria-label="title.code"
          :aria-current="activeIndex === idx"
          @click="activeIndex = idx"
        >
          <div
            class="aspect-[3/2] rounded-[14px] overflow-hidden bg-fill transition-[opacity,filter,box-shadow] duration-300 [transition-timing-function:var(--ease-out)]"
            :class="[
              activeIndex === idx
                ? 'shadow-[0_14px_30px_-16px_rgba(0,0,0,0.45)]'
                : 'opacity-[0.78] sm:group-hover/rail:opacity-45 sm:group-hover/rail:saturate-[0.6] sm:group-hover/thumb:!opacity-100 sm:group-hover/thumb:!saturate-100 sm:group-hover/thumb:shadow-[0_14px_30px_-16px_rgba(0,0,0,0.4)]',
              title.magnet_status === 'dead' ? 'grayscale !opacity-40' : '',
            ]"
          >
            <!-- Fixed box + contain: every thumbnail gets the same height and
                 an abnormal cover (portrait, wrong dims) letterboxes inside
                 instead of stretching the rail. Never object-cover. -->
            <img
              v-if="title.cover_url && !thumbErrors[title.code]"
              :src="title.cover_thumb_url || `/api/cover/${title.code}?thumb=1`"
              :alt="title.code"
              class="h-full w-full object-contain"
              decoding="async"
              @error="thumbErrors[title.code] = true"
            />
            <div
              v-else
              class="flex h-full items-center justify-center p-2 text-center"
            >
              <span class="text-[11px] font-semibold text-foreground/50">{{ title.code }}</span>
            </div>
          </div>
          <div class="mt-2.5 flex items-center gap-1.5 px-0.5 whitespace-nowrap">
            <span
              class="h-1.5 rounded-full bg-accent transition-[width,opacity] duration-300 [transition-timing-function:var(--ease-out)]"
              :class="activeIndex === idx ? 'w-1.5 opacity-100' : 'w-0 opacity-0'"
            />
            <span
              class="text-[13px] font-semibold truncate transition-colors"
              :class="activeIndex === idx ? 'text-foreground' : 'text-foreground-muted group-hover/thumb:text-foreground'"
            >{{ title.code }}</span>
            <span class="ml-auto text-[12px] text-foreground-muted/70 tabular-nums">{{ shortDate(title.date) }}</span>
          </div>
        </button>
        <div v-if="trailPad > 0" class="shrink-0 h-px" :style="{ width: `${trailPad}px` }" />
      </div>
    </div>
  </section>
</template>

<script setup lang="ts">
import type { Star, Title } from '~/types/api'
import {
  heroLqipSrc,
  heroSrc,
  heroSrcset,
  heroSrcTier,
  isHeroCoverReady,
  markHeroCoverReady,
  prefetchHeroCover,
  prefetchHeroNeighbors,
} from '~/utils/heroCover'

const props = defineProps<{
  star: Star
  index?: number
}>()

const emit = defineEmits<{
  (e: 'play', magnet: string, code: string, starCode: string): void
  (e: 'deleted', code: string): void
  (e: 'social', code: string): void
}>()

const { track } = useTrack()
const { add: addLog } = useEventLog()

const id = computed(() => props.star.code.toLowerCase())
const activeIndex = ref(0)
const activeTitle = computed(() => props.star.titles?.[activeIndex.value] || null)
const total = computed(() => props.star.titles?.length ?? 0)

const heroStageRef = ref<HTMLElement | null>(null)
const stepAnimLock = ref(false)
let stepAnimTimer: ReturnType<typeof setTimeout> | null = null
let heroPaintStart = 0
let heroPaintMeta: { code: string; cacheHit: boolean } | null = null

function step(delta: number) {
  if (stepAnimLock.value) return
  const next = activeIndex.value + delta
  if (next < 0 || next >= total.value) return
  const nextTitle = props.star.titles?.[next]
  const cacheHit = !!(nextTitle && isHeroCoverReady(nextTitle.code))
  if (nextTitle) {
    heroPaintStart = performance.now()
    heroPaintMeta = { code: nextTitle.code, cacheHit }
  }
  activeIndex.value = next
  stepAnimLock.value = true
  if (stepAnimTimer) clearTimeout(stepAnimTimer)
  stepAnimTimer = setTimeout(() => {
    stepAnimLock.value = false
    stepAnimTimer = null
  }, cacheHit ? 180 : 300)
  revealThumb(next)
  if (cacheHit && nextTitle) {
    heroLoaded.value = true
    finishHeroPaint(nextTitle)
  }
}

const controlsShown = ref(false)
let controlsTimer: ReturnType<typeof setTimeout> | null = null

function showControlsBriefly() {
  controlsShown.value = true
  if (controlsTimer) clearTimeout(controlsTimer)
  controlsTimer = setTimeout(() => { controlsShown.value = false }, 1600)
}

function clampDrag(dx: number): number {
  const atStart = activeIndex.value <= 0 && dx > 0
  const atEnd = activeIndex.value >= total.value - 1 && dx < 0
  const damp = atStart || atEnd ? 0.32 : 1
  return dx * damp
}

const {
  dragX,
  dragging,
  onPointerDown,
  onPointerMove,
  onPointerUp,
  onPointerCancel,
  onWheel,
  onKeydown,
} = useHeroStepGesture({
  canStep: () => total.value > 1 && !stepAnimLock.value,
  stageWidth: () => heroStageRef.value?.clientWidth ?? 360,
  onStep: (delta) => step(delta),
  onShowControls: showControlsBriefly,
})

// Keep the stepped-to card in view without nudging the page vertically.
function revealThumb(idx: number) {
  const row = rowRef.value
  if (!row || !thumbStride.value) return
  const left = idx * thumbStride.value - (row.clientWidth - thumbItemWidth.value) / 2
  row.scrollTo({ left: Math.max(0, left), behavior: 'auto' })
}

const activeImgError = ref(false)
const thumbErrors = ref<Record<string, boolean>>({})

// Hero fades in once decoded instead of painting top-to-bottom. A cached
// image can finish before the listener runs, so also trust `complete`.
const heroImg = ref<HTMLImageElement | null>(null)
const heroLoaded = ref(false)
watch(heroImg, (img) => {
  if (img?.complete && img.naturalWidth > 0) {
    void onHeroImgLoad({ target: img } as Event)
  }
}, { flush: 'post' })

function finishHeroPaint(t: Title) {
  if (!heroPaintMeta || heroPaintMeta.code !== t.code) return
  const paint_ms = Math.round(performance.now() - heroPaintStart)
  track('hero_step', {
    code: t.code,
    star_code: props.star.code,
    meta: {
      paint_ms,
      cache_hit: heroPaintMeta.cacheHit,
      src_tier: heroSrcTier(t),
    },
  })
  heroPaintMeta = null
}

async function onHeroImgLoad(e: Event) {
  const img = e.target as HTMLImageElement
  const t = activeTitle.value
  if (!t) return
  try {
    if (typeof img.decode === 'function') await img.decode()
  } catch {
    // Truncated or unsupported — still show if pixels landed.
  }
  markHeroCoverReady(t.code)
  if (activeTitle.value?.code === t.code) heroLoaded.value = true
  finishHeroPaint(t)
}

const activeIsHd = computed(() => {
  const t = activeTitle.value
  if (!t || t.magnet_status === 'dead') return false
  const res = t.resolution?.toLowerCase() ?? ''
  return res.includes('1080') || res.includes('4k')
})

// Reserve the hero's box at its true aspect ratio so the layout never
// jumps when bytes arrive. Fallback 3/2: virtually all covers are
// ~800x537 landscape jackets, not 2:3 portraits. (Gallery thumbnails use
// a fixed 3/2 box + object-contain instead, so abnormal covers can't
// stretch the rail.)
function coverAR(t: Title): string {
  return t.cover_w && t.cover_h ? `${t.cover_w} / ${t.cover_h}` : '3 / 2'
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
  prefetchHeroNeighbors(props.star.titles ?? [], activeIndex.value)
})

onUnmounted(() => {
  rowResizeObserver?.disconnect()
  if (controlsTimer) clearTimeout(controlsTimer)
  if (stepAnimTimer) clearTimeout(stepAnimTimer)
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

watch(activeIndex, (idx) => {
  activeImgError.value = false
  prefetchHeroNeighbors(props.star.titles ?? [], idx)
})

watch(() => activeTitle.value?.code, (code) => {
  if (!code) return
  activeImgError.value = false
  const t = activeTitle.value
  if (!t) return
  if (isHeroCoverReady(code)) {
    heroLoaded.value = true
  } else {
    heroLoaded.value = false
    prefetchHeroCover(t)
  }
  if (!heroPaintMeta || heroPaintMeta.code !== code) {
    heroPaintStart = performance.now()
    heroPaintMeta = { code, cacheHit: isHeroCoverReady(code) }
  }
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

function shortDate(dateStr?: string): string {
  const parts = dateStr?.split('/')
  if (!parts || parts.length !== 3) return ''
  return `${parts[2].slice(2)}.${parts[1].padStart(2, '0')}.${parts[0].padStart(2, '0')}`
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
