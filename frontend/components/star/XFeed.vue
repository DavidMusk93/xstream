<template>
  <div class="x-feed mt-8 sm:mt-10">
    <div class="flex items-center gap-2.5 px-1 min-w-0">
      <a
        :href="profileUrl"
        target="_blank"
        rel="noopener noreferrer"
        class="group/xh flex items-center gap-2 min-w-0"
        :aria-label="`${star} on X`"
        :title="profile.name || undefined"
      >
        <span class="w-6 h-6 shrink-0 rounded-full overflow-hidden bg-foreground text-white flex items-center justify-center">
          <img
            v-if="profile.avatar && !avatarError"
            :src="profile.avatar"
            alt=""
            width="24"
            height="24"
            class="w-full h-auto block"
            referrerpolicy="no-referrer"
            loading="lazy"
            decoding="async"
            @error="avatarError = true"
          />
          <XGlyph v-else class="w-3 h-3" />
        </span>
        <span class="text-[14px] font-semibold text-foreground truncate group-hover/xh:underline underline-offset-2">{{ star }}</span>
        <span v-if="profile.handle" class="hidden sm:inline text-[13px] text-foreground-muted truncate">@{{ profile.handle }}</span>
      </a>
      <span class="h-px flex-1 min-w-4 bg-black/[0.06]" />
      <span v-if="profile.checked_at" class="font-mono text-[12px] tracking-[0.04em] text-foreground-muted/80 whitespace-nowrap" :title="fullTime(profile.checked_at)">
        {{ agoTime(profile.checked_at) }}
      </span>
    </div>

    <!-- One fixed-height strip: photos keep their natural ratio (width
         follows the image), text posts become pull-quotes of the same height.
         Nothing is elided: long text scrolls inside its tile. -->
    <div class="mt-3 -mx-1 px-1 flex gap-3 h-[224px] sm:h-[260px] overflow-x-auto overflow-y-hidden scrollbar-hide snap-x snap-mandatory fade-edge-r">
      <div
        v-for="post in profile.posts"
        :key="post.id"
        class="x-post group/post relative h-full shrink-0 snap-start rounded-[18px] overflow-hidden"
        :class="showImage(post) ? 'bg-fill' : ['bg-white shadow-card', quoteWidth(body(post))]"
        :title="post.en && post.text ? post.text : undefined"
      >
        <template v-if="showImage(post)">
          <!-- Hidden until fully loaded: twimg JPEGs paint top-down while
               downloading, which showed as half images on slow links -->
          <img
            :src="post.media[0]"
            alt=""
            class="block h-full w-auto max-w-[min(440px,78vw)] object-contain transition-opacity duration-500 [transition-timing-function:var(--ease-out)]"
            :class="loaded[post.id] ? 'opacity-100' : 'opacity-0'"
            :style="loaded[post.id] ? undefined : { aspectRatio: '3 / 4' }"
            referrerpolicy="no-referrer"
            loading="lazy"
            decoding="async"
            fetchpriority="low"
            @load="onImgLoad(post.id, $event)"
            @error="mediaError[post.id] = true"
          />
          <!-- Caption: 3 lines at rest; hover (pointer) or tap opens the full
               text over a deeper scrim, scrollable when it is long -->
          <div
            class="absolute inset-0 flex flex-col justify-end transition-colors duration-300"
            :class="open[post.id] ? 'bg-black/55' : ''"
            :role="body(post) ? 'button' : undefined"
            :tabindex="body(post) ? 0 : undefined"
            :aria-expanded="body(post) ? !!open[post.id] : undefined"
            aria-label="Show full caption"
            @click="!canHover && toggle(post.id, $event)"
            @keydown.enter.prevent="toggle(post.id, $event)"
            @mouseenter="canHover && toggle(post.id, $event, true)"
            @mouseleave="open[post.id] = false"
          >
            <div class="min-h-0 flex flex-col px-3 pb-2.5 pt-10 text-white" :class="open[post.id] ? '' : 'bg-gradient-to-t from-black/70 via-black/35 to-transparent'">
              <p
                v-if="body(post)"
                class="min-h-0 text-[13px] leading-[1.45] font-medium whitespace-pre-line break-words [overflow-wrap:anywhere]"
                :class="open[post.id] ? 'overflow-y-auto overscroll-contain scrollbar-hide' : 'line-clamp-3'"
              >{{ body(post) }}</p>
              <div class="mt-1 shrink-0 flex items-center gap-3 font-mono text-[11px] tracking-[0.03em] text-white/75 tabular-nums">
                <time v-if="post.posted_at" :datetime="post.posted_at" :title="fullTime(post.posted_at)">{{ relTime(post.posted_at) }}</time>
                <span v-if="post.stats?.likes != null" class="ml-auto inline-flex items-center gap-1">
                  <svg width="11" height="11" viewBox="0 0 24 24" fill="currentColor"><path :d="HEART" /></svg>{{ compact(post.stats.likes) }}
                </span>
              </div>
            </div>
          </div>
          <div class="absolute top-2.5 left-2.5 flex gap-1.5 pointer-events-none">
            <span v-if="badge(post)" class="chip bg-white/85 text-foreground backdrop-blur-sm">{{ badge(post) }}</span>
            <span v-if="post.media.length > 1" class="chip bg-black/45 text-white backdrop-blur-sm tabular-nums">+{{ post.media.length - 1 }}</span>
          </div>
          <a
            v-if="post.url"
            :href="post.url"
            target="_blank"
            rel="noopener noreferrer"
            class="absolute top-2 right-2 w-7 h-7 rounded-full flex items-center justify-center bg-black/35 text-white backdrop-blur-sm hover:bg-black/55 transition-colors"
            aria-label="Open post on X"
          >
            <XGlyph class="w-3 h-3" />
          </a>
        </template>

        <div v-else class="h-full flex flex-col p-4 sm:p-5">
          <div class="flex items-center gap-2 font-mono text-[11px] tracking-[0.04em] text-foreground-muted tabular-nums">
            <time v-if="post.posted_at" :datetime="post.posted_at" :title="fullTime(post.posted_at)">{{ relTime(post.posted_at) }}</time>
            <span v-if="badge(post)" class="chip bg-black/[0.05] text-foreground font-sans">{{ badge(post) }}</span>
            <a
              v-if="post.url"
              :href="post.url"
              target="_blank"
              rel="noopener noreferrer"
              class="ml-auto -mr-1.5 -my-1 w-7 h-7 rounded-full flex items-center justify-center text-foreground/30 hover:text-foreground hover:bg-black/[0.05] transition-colors"
              aria-label="Open post on X"
            >
              <XGlyph class="w-3 h-3" />
            </a>
          </div>
          <p
            v-overflow
            class="quote mt-3 flex-1 min-h-0 overflow-y-auto overscroll-contain scrollbar-hide text-foreground whitespace-pre-line break-words [overflow-wrap:anywhere]"
            :class="quoteClass(body(post))"
          >
            <template v-for="(tok, k) in tokenize(body(post))" :key="k">
              <span v-if="tok.entity" class="text-info">{{ tok.text }}</span>
              <template v-else>{{ tok.text }}</template>
            </template>
          </p>
          <div v-if="post.stats?.likes != null || post.stats?.views != null" class="pt-3 flex items-center gap-3 text-[12px] font-medium text-foreground-muted tabular-nums">
            <span v-if="post.stats.likes != null" class="inline-flex items-center gap-1" :title="`${post.stats.likes.toLocaleString()} likes`">
              <svg width="12" height="12" viewBox="0 0 24 24" fill="currentColor" class="text-accent/80"><path :d="HEART" /></svg>{{ compact(post.stats.likes) }}
            </span>
            <span v-if="post.stats.views != null" :title="`${post.stats.views.toLocaleString()} views`">{{ compact(post.stats.views) }} views</span>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import type { XPost, XProfile } from '~/types/api'

const props = defineProps<{ profile: XProfile; star: string }>()

const HEART = 'M12 21.2l-1.4-1.3C5.4 15.4 2 12.3 2 8.5 2 5.4 4.4 3 7.5 3c1.7 0 3.4.8 4.5 2.1C13.1 3.8 14.8 3 16.5 3 19.6 3 22 5.4 22 8.5c0 3.8-3.4 6.9-8.6 11.4L12 21.2z'

const avatarError = ref(false)
const loaded = reactive<Record<string, boolean>>({})
const open = reactive<Record<string, boolean>>({})
const canHover = import.meta.client && window.matchMedia('(hover: hover)').matches
const mediaError = reactive<Record<string, boolean>>({})

const profileUrl = computed(() => (props.profile.handle ? `https://x.com/${props.profile.handle}` : undefined))

function body(p: XPost): string {
  return p.en || p.text
}

// Opens only when the 3-line caption is actually truncated; a short
// caption has nothing to reveal and would just darken the photo.
function toggle(id: string, e: Event, to?: boolean) {
  const next = to ?? !open[id]
  if (next) {
    const p = (e.currentTarget as HTMLElement).querySelector('p')
    if (!p || p.scrollHeight <= p.clientHeight + 1) return
  }
  open[id] = next
}

// Marks scrollable quotes so CSS fades the cut edge until the end is reached.
function syncOverflow(el: HTMLElement) {
  el.toggleAttribute('data-overflow', el.scrollHeight > el.clientHeight + 1)
  el.toggleAttribute('data-end', el.scrollTop + el.clientHeight >= el.scrollHeight - 2)
}
const vOverflow = {
  mounted(el: HTMLElement) {
    syncOverflow(el)
    el.addEventListener('scroll', () => syncOverflow(el), { passive: true })
  },
  updated: syncOverflow,
}

function showImage(p: XPost) {
  return p.media.length > 0 && !mediaError[p.id]
}

async function onImgLoad(id: string, e: Event) {
  const img = e.target as HTMLImageElement
  // A truncated response can still fire load; only reveal fully decoded images.
  try { await img.decode() } catch { mediaError[id] = true; return }
  if (!img.naturalWidth) { mediaError[id] = true; return }
  loaded[id] = true
}

function badge(p: XPost): string {
  if (p.pinned) return 'Pinned'
  const h = props.profile.handle
  if (p.author && h && p.author.toLowerCase() !== h.toLowerCase()) return 'Repost'
  return ''
}

// Pull-quote scale: short posts read as a headline, long ones as body text.
function quoteClass(text: string): string {
  const n = [...text].length
  if (n <= 28) return 'text-[21px] sm:text-[23px] leading-[1.3] font-semibold tracking-[-0.01em]'
  if (n <= 80) return 'text-[17px] leading-[1.45] font-medium'
  if (n <= 200) return 'text-[15px] leading-[1.5]'
  return 'text-[14px] leading-[1.55]'
}

// Long posts get a wider tile so most of them fit without scrolling.
function quoteWidth(text: string): string {
  const n = [...text].length
  if (n <= 80) return 'w-[216px] sm:w-[248px]'
  if (n <= 200) return 'w-[256px] sm:w-[304px]'
  return 'w-[288px] sm:w-[360px]'
}

function compact(n: number) {
  if (n < 1000) return String(n)
  if (n < 1e6) return `${+(n / 1e3).toFixed(n < 1e4 ? 1 : 0)}K`
  return `${+(n / 1e6).toFixed(n < 1e7 ? 1 : 0)}M`
}

interface Token { text: string; entity?: boolean }
const TOKEN_RE = /(https?:\/\/[^\s<>"']+[^\s<>"'.,;:!?)\]」』）】])|(^|[^\w@])@(\w{1,15})|(^|[^\w&#])#([\p{L}\p{N}_]+)/gu

// The whole card links to the post, so entities are colored, not nested links.
function tokenize(text: string): Token[] {
  const out: Token[] = []
  let last = 0
  for (const m of text.matchAll(TOKEN_RE)) {
    let start = m.index!
    let tok: Token
    if (m[1]) {
      const display = m[1].replace(/^https?:\/\/(www\.)?/, '')
      tok = { text: display.length > 26 ? `${display.slice(0, 25)}…` : display, entity: true }
    } else if (m[3]) {
      start += m[2].length
      tok = { text: `@${m[3]}`, entity: true }
    } else {
      start += m[4].length
      tok = { text: `#${m[5]}`, entity: true }
    }
    if (start > last) out.push({ text: text.slice(last, start) })
    out.push(tok)
    last = m.index! + m[0].length
  }
  if (last < text.length) out.push({ text: text.slice(last) })
  return out
}

function relTime(iso: string): string {
  const t = Date.parse(iso)
  if (Number.isNaN(t)) return ''
  const s = Math.max(0, (Date.now() - t) / 1000)
  if (s < 60) return 'now'
  if (s < 3600) return `${Math.floor(s / 60)}m`
  if (s < 86400) return `${Math.floor(s / 3600)}h`
  if (s < 86400 * 7) return `${Math.floor(s / 86400)}d`
  const d = new Date(t)
  const sameYear = d.getFullYear() === new Date().getFullYear()
  return d.toLocaleDateString(undefined, sameYear ? { month: 'short', day: 'numeric' } : { year: 'numeric', month: 'short', day: 'numeric' })
}

function agoTime(iso: string): string {
  const rel = relTime(iso)
  return /^\d+[mhd]$/.test(rel) ? `${rel} ago` : rel
}

function fullTime(iso: string): string {
  const t = Date.parse(iso)
  return Number.isNaN(t) ? '' : new Date(t).toLocaleString()
}
</script>

<style scoped>
.quote[data-overflow]:not([data-end]) {
  -webkit-mask-image: linear-gradient(to bottom, #000 calc(100% - 24px), transparent);
  mask-image: linear-gradient(to bottom, #000 calc(100% - 24px), transparent);
}
</style>
