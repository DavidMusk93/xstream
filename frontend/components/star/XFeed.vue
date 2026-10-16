<template>
  <div class="mt-10 sm:mt-12">
    <div class="flex items-center gap-3 px-1">
      <a
        :href="profileUrl"
        target="_blank"
        rel="noopener noreferrer"
        class="group/xh flex items-center gap-2.5 min-w-0"
        :aria-label="`${profile.name || star} on X`"
      >
        <span class="relative w-8 h-8 shrink-0 rounded-full overflow-hidden bg-foreground text-white flex items-center justify-center">
          <img
            v-if="profile.avatar && !avatarError"
            :src="profile.avatar"
            alt=""
            width="32"
            height="32"
            class="w-full h-auto block"
            referrerpolicy="no-referrer"
            loading="lazy"
            decoding="async"
            @error="avatarError = true"
          />
          <XGlyph v-else class="w-3.5 h-3.5" />
        </span>
        <span class="min-w-0 leading-tight">
          <span class="block text-[14px] font-semibold text-foreground truncate group-hover/xh:underline underline-offset-2">
            {{ profile.name || star }}
          </span>
          <span v-if="profile.handle" class="block text-[12px] text-foreground-muted truncate">@{{ profile.handle }}</span>
        </span>
      </a>
      <span class="h-px flex-1 bg-black/[0.06]" />
      <span v-if="profile.checked_at" class="font-mono text-[12px] tracking-[0.04em] text-foreground-muted/80 tabular-nums whitespace-nowrap" :title="fullTime(profile.checked_at)">
        Updated {{ agoTime(profile.checked_at) }}
      </span>
    </div>

    <div class="mt-4 -mx-1 px-1 flex gap-4 items-stretch overflow-x-auto scrollbar-hide snap-x snap-mandatory pt-1 pb-3 fade-edge-r">
      <article
        v-for="(post, i) in profile.posts"
        :key="post.id"
        class="x-post shrink-0 snap-start w-[276px] sm:w-[320px] flex flex-col rounded-[20px] bg-white shadow-card p-4 sm:p-5"
      >
        <header class="flex items-center gap-2 font-mono text-[12px] tracking-[0.04em] text-foreground-muted tabular-nums">
          <span class="text-accent">{{ String(i + 1).padStart(2, '0') }}</span>
          <time v-if="post.posted_at" :datetime="post.posted_at" :title="fullTime(post.posted_at)">{{ relTime(post.posted_at) }}</time>
          <span v-if="post.pinned" class="chip bg-black/[0.05] text-foreground font-sans">Pinned</span>
          <span v-else-if="isRepost(post)" class="chip bg-black/[0.05] text-foreground font-sans" :title="`@${post.author}`">Repost</span>
          <a
            v-if="post.url"
            :href="post.url"
            target="_blank"
            rel="noopener noreferrer"
            class="ml-auto -mr-1.5 w-7 h-7 rounded-full flex items-center justify-center text-foreground-muted hover:text-foreground hover:bg-black/[0.05] transition-colors"
            aria-label="Open post on X"
          >
            <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round">
              <path d="M7 17 17 7" /><polyline points="8 7 17 7 17 16" />
            </svg>
          </a>
        </header>

        <p
          v-if="post.text"
          class="mt-3 text-[15px] leading-[1.55] text-foreground whitespace-pre-line break-words [overflow-wrap:anywhere]"
          :class="expanded[post.id] ? '' : 'line-clamp-6'"
        >
          <template v-for="(tok, k) in tokenize(post.text)" :key="k">
            <a
              v-if="tok.href"
              :href="tok.href"
              target="_blank"
              rel="noopener noreferrer nofollow"
              class="text-info hover:underline underline-offset-2"
            >{{ tok.text }}</a>
            <template v-else>{{ tok.text }}</template>
          </template>
        </p>
        <button
          v-if="post.text.length > 220 || post.text.split('\n').length > 6"
          class="self-start mt-1 text-[13px] font-medium text-foreground-muted hover:text-foreground transition-colors"
          @click="expanded[post.id] = !expanded[post.id]"
        >
          {{ expanded[post.id] ? 'Show less' : 'Show more' }}
        </button>

        <!-- One image, natural ratio: the rest are a count, not more bytes -->
        <div v-if="post.media.length && !mediaError[post.id]" class="relative mt-3 self-start max-w-full">
          <img
            :src="post.media[0]"
            alt=""
            class="block max-w-full max-h-[220px] w-auto h-auto rounded-[12px] bg-fill"
            referrerpolicy="no-referrer"
            loading="lazy"
            decoding="async"
            @error="mediaError[post.id] = true"
          />
          <span v-if="post.media.length > 1" class="absolute right-2 bottom-2 chip bg-black/55 text-white backdrop-blur-sm tabular-nums">
            +{{ post.media.length - 1 }}
          </span>
        </div>

        <footer v-if="hasStats(post)" class="mt-auto pt-4 flex items-center gap-4 text-[12px] font-medium text-foreground-muted tabular-nums">
          <span v-for="s in statItems(post)" :key="s.key" class="inline-flex items-center gap-1.5" :title="`${s.value.toLocaleString()} ${s.key}`">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" v-html="ICONS[s.key]" />
            {{ compact(s.value) }}
          </span>
        </footer>
      </article>
    </div>
  </div>
</template>

<script setup lang="ts">
import type { XPost, XProfile } from '~/types/api'

const props = defineProps<{ profile: XProfile; star: string }>()

const avatarError = ref(false)
const expanded = reactive<Record<string, boolean>>({})
const mediaError = reactive<Record<string, boolean>>({})

const profileUrl = computed(() => (props.profile.handle ? `https://x.com/${props.profile.handle}` : undefined))

function isRepost(p: XPost) {
  return !!p.author && !!props.profile.handle && p.author.toLowerCase() !== props.profile.handle.toLowerCase()
}

// Static, trusted markup only — never injected content.
const ICONS: Record<string, string> = {
  replies: '<path d="M21 11.5a8.4 8.4 0 0 1-9 8.4 9 9 0 0 1-4-.9L3 20l1.1-4A8.4 8.4 0 1 1 21 11.5z"/>',
  reposts: '<polyline points="17 2 21 6 17 10"/><path d="M3 11V9a3 3 0 0 1 3-3h15"/><polyline points="7 22 3 18 7 14"/><path d="M21 13v2a3 3 0 0 1-3 3H3"/>',
  likes: '<path d="M20.84 4.61a5.5 5.5 0 0 0-7.78 0L12 5.67l-1.06-1.06a5.5 5.5 0 0 0-7.78 7.78l1.06 1.06L12 21.23l7.78-7.78 1.06-1.06a5.5 5.5 0 0 0 0-7.78z"/>',
  views: '<line x1="6" y1="20" x2="6" y2="13"/><line x1="12" y1="20" x2="12" y2="4"/><line x1="18" y1="20" x2="18" y2="10"/>',
}
const STAT_ORDER = ['replies', 'reposts', 'likes', 'views'] as const

function hasStats(p: XPost) {
  return STAT_ORDER.some(k => p.stats?.[k] != null)
}

function statItems(p: XPost) {
  return STAT_ORDER.filter(k => p.stats?.[k] != null).map(k => ({ key: k, value: p.stats[k]! }))
}

function compact(n: number) {
  if (n < 1000) return String(n)
  if (n < 1e6) return `${+(n / 1e3).toFixed(n < 1e4 ? 1 : 0)}K`
  return `${+(n / 1e6).toFixed(n < 1e7 ? 1 : 0)}M`
}

interface Token { text: string; href?: string }
const TOKEN_RE = /(https?:\/\/[^\s<>"']+[^\s<>"'.,;:!?)\]」』）】])|(^|[^\w@])@(\w{1,15})|(^|[^\w&#])#([\p{L}\p{N}_]+)/gu

// Text is rendered through interpolation, so links are the only markup and
// their hrefs are http(s) or x.com by construction.
function tokenize(text: string): Token[] {
  const out: Token[] = []
  let last = 0
  for (const m of text.matchAll(TOKEN_RE)) {
    let start = m.index!
    let tok: Token
    if (m[1]) {
      const display = m[1].replace(/^https?:\/\/(www\.)?/, '')
      tok = { text: display.length > 30 ? `${display.slice(0, 29)}…` : display, href: m[1] }
    } else if (m[3]) {
      start += m[2].length
      tok = { text: `@${m[3]}`, href: `https://x.com/${m[3]}` }
    } else {
      start += m[4].length
      tok = { text: `#${m[5]}`, href: `https://x.com/hashtag/${encodeURIComponent(m[5])}` }
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
