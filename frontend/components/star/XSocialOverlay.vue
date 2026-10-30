<template>
  <Teleport to="body">
    <Transition name="xsocial" :duration="{ enter: 450, leave: 220 }">
      <div
        v-if="open"
        class="xs-root fixed inset-0 z-[95] flex items-end sm:items-center justify-center sm:p-6"
        @pointerdown.self="open = false"
      >
        <div class="xs-scrim absolute inset-0 bg-black/25 pointer-events-none" />
        <div
          role="dialog"
          aria-modal="true"
          aria-label="X posts"
          class="xs-panel relative w-full sm:max-w-[640px] h-[92dvh] sm:h-auto sm:max-h-[88dvh] flex flex-col bg-white rounded-t-[28px] sm:rounded-[28px] shadow-float pb-[env(safe-area-inset-bottom)]"
        >
          <div class="sm:hidden flex justify-center pt-2.5 shrink-0">
            <span class="w-9 h-1 rounded-full bg-black/[0.12]" />
          </div>

          <!-- Header -->
          <div class="shrink-0 flex items-center justify-between gap-3 px-5 sm:px-6 pt-3 sm:pt-5">
            <div class="min-w-0">
              <h2 class="text-[22px] font-bold text-foreground leading-tight flex items-center gap-2">
                <XGlyph class="w-[18px] h-[18px]" />
                X posts
              </h2>
              <p class="mt-0.5 text-[13px] text-foreground-muted tabular-nums">
                {{ feedPostCount }} post{{ feedPostCount === 1 ? '' : 's' }}
                · {{ sourceCount }} account{{ sourceCount === 1 ? '' : 's' }}
              </p>
            </div>
            <div class="flex items-center gap-2 shrink-0">
              <button class="btn btn-sm btn-dark" @click="emit('inject', filter)">
                Inject
              </button>
              <button class="btn-icon bg-black/[0.04] text-foreground-muted" aria-label="Close" @click="open = false">
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round">
                  <line x1="18" y1="6" x2="6" y2="18" /><line x1="6" y1="6" x2="18" y2="18" />
                </svg>
              </button>
            </div>
          </div>

          <!-- Scope: stars vs body creators, then the per-star chips -->
          <div v-if="kinds.length > 1" class="shrink-0 mt-3 px-5 sm:px-6 flex gap-1.5">
            <button
              v-for="k in kinds"
              :key="k.id"
              class="chip shrink-0 transition-colors"
              :class="kind === k.id ? 'bg-foreground text-white' : 'bg-black/[0.05] text-foreground hover:bg-black/[0.08]'"
              @click="kind = k.id"
            >{{ k.label }}<span class="ml-1 opacity-60 tabular-nums">{{ k.count }}</span></button>
          </div>

          <div v-if="kind === 'stars' && withPosts.length > 1" class="shrink-0 mt-2 px-5 sm:px-6 flex gap-2 overflow-x-auto scrollbar-hide">
            <button
              class="chip shrink-0 transition-colors"
              :class="filter === '' ? 'bg-foreground text-white' : 'bg-black/[0.05] text-foreground hover:bg-black/[0.08]'"
              @click="filter = ''"
            >All</button>
            <button
              v-for="s in withPosts"
              :key="s.code"
              class="chip shrink-0 transition-colors"
              :class="filter === s.code ? 'bg-foreground text-white' : 'bg-black/[0.05] text-foreground hover:bg-black/[0.08]'"
              @click="filter = filter === s.code ? '' : s.code"
            >{{ s.name }}</button>
          </div>

          <!-- Feed -->
          <div class="flex-1 min-h-0 mt-4 overflow-y-auto overscroll-contain px-4 sm:px-6 pb-6">
            <!-- Pornographic creators: one block per account, posts time-sorted inside -->
            <div v-if="kind === 'creators' && creatorGroups.length" class="space-y-6">
              <section v-for="g in creatorGroups" :key="g.handle">
                <div class="flex items-center gap-2.5 min-w-0 px-0.5">
                  <a
                    :href="`https://x.com/${g.handle}`"
                    target="_blank"
                    rel="noopener noreferrer"
                    class="flex items-center gap-2.5 min-w-0 group/xa flex-1"
                  >
                    <span class="w-9 h-9 shrink-0 rounded-full overflow-hidden bg-foreground text-white flex items-center justify-center">
                      <img
                        v-if="g.avatar && !failed[`av:c:${g.handle}`]"
                        :src="g.avatar"
                        alt=""
                        width="36"
                        height="36"
                        class="w-full h-auto block"
                        loading="lazy"
                        decoding="async"
                        @error="onImgError(`av:c:${g.handle}`, $event)"
                      />
                      <XGlyph v-else class="w-4 h-4" />
                    </span>
                    <span class="min-w-0">
                      <span class="block text-[15px] font-semibold text-foreground truncate leading-tight group-hover/xa:underline underline-offset-2">{{ g.name }}</span>
                      <span class="block text-[12px] text-foreground-muted truncate leading-tight">@{{ g.handle }} · {{ g.entries.length }} post{{ g.entries.length === 1 ? '' : 's' }}</span>
                    </span>
                  </a>
                  <button
                    class="chip bg-black/[0.05] text-foreground shrink-0 hover:bg-danger/10 hover:text-danger transition-colors"
                    :title="`Unfollow @${g.handle}`"
                    :disabled="removing === g.handle"
                    @click="unfollow(g.handle)"
                  >Unfollow</button>
                </div>
                <div class="mt-3 space-y-3">
                  <article
                    v-for="e in g.entries"
                    :key="`${e.key}:${e.post.id}`"
                    class="rounded-[18px] border border-black/[0.06] bg-white p-4"
                  >
                    <div class="flex items-center gap-2 min-w-0">
                      <span v-if="badge(e)" class="chip bg-black/[0.05] text-foreground shrink-0">{{ badge(e) }}</span>
                      <time
                        v-if="e.post.posted_at"
                        :datetime="e.post.posted_at"
                        :title="fullTime(e.post.posted_at)"
                        class="font-mono text-[11px] tracking-[0.03em] text-foreground-muted tabular-nums"
                      >{{ relTime(e.post.posted_at) }}</time>
                      <a
                        v-if="e.post.url"
                        :href="e.post.url"
                        target="_blank"
                        rel="noopener noreferrer"
                        class="ml-auto shrink-0 w-7 h-7 -mr-1 rounded-full flex items-center justify-center text-foreground/30 hover:text-foreground hover:bg-black/[0.05] transition-colors"
                        aria-label="Open post on X"
                      >
                        <XGlyph class="w-3 h-3" />
                      </a>
                    </div>
                    <p
                      v-if="body(e.post)"
                      class="mt-2 text-[15px] leading-[1.5] text-foreground whitespace-pre-line break-words [overflow-wrap:anywhere]"
                      :title="e.post.en && e.post.text ? e.post.text : undefined"
                    >
                      <template v-for="(tok, k) in tokenize(body(e.post))" :key="k">
                        <span v-if="tok.entity" class="text-info">{{ tok.text }}</span>
                        <template v-else>{{ tok.text }}</template>
                      </template>
                    </p>
                    <div
                      v-if="shownMedia(e.post).length"
                      class="mt-3 grid gap-2"
                      :class="shownMedia(e.post).length > 1 ? 'grid-cols-2' : 'grid-cols-1'"
                    >
                      <div
                        v-for="(src, i) in shownMedia(e.post)"
                        :key="i"
                        class="rounded-[14px] overflow-hidden bg-fill"
                      >
                        <img
                          :src="src"
                          alt=""
                          class="block w-full h-auto transition-opacity duration-500 [transition-timing-function:var(--ease-out)]"
                          :class="loaded[`${e.post.id}:${i}`] ? 'opacity-100' : 'opacity-0'"
                          loading="lazy"
                          decoding="async"
                          @load="onImgLoad(`${e.post.id}:${i}`, $event)"
                          @error="onImgError(`${e.post.id}:${i}`, $event)"
                        />
                      </div>
                    </div>
                    <div v-if="e.post.stats?.likes != null || e.post.stats?.views != null" class="mt-3 flex items-center gap-3 text-[12px] font-medium text-foreground-muted tabular-nums">
                      <span v-if="e.post.stats.likes != null" class="inline-flex items-center gap-1" :title="`${e.post.stats.likes.toLocaleString()} likes`">
                        <svg width="12" height="12" viewBox="0 0 24 24" fill="currentColor" class="text-accent/80"><path :d="HEART" /></svg>{{ compact(e.post.stats.likes) }}
                      </span>
                      <span v-if="e.post.stats.views != null" :title="`${e.post.stats.views.toLocaleString()} views`">{{ compact(e.post.stats.views) }} views</span>
                    </div>
                  </article>
                </div>
              </section>
            </div>
            <div v-else-if="entries.length" class="space-y-4">
              <article
                v-for="e in entries"
                :key="`${e.key}:${e.post.id}`"
                class="rounded-[18px] border border-black/[0.06] bg-white p-4"
              >
                <!-- Author line -->
                <div class="flex items-center gap-2.5 min-w-0">
                  <a
                    v-if="e.handle"
                    :href="`https://x.com/${e.handle}`"
                    target="_blank"
                    rel="noopener noreferrer"
                    class="flex items-center gap-2.5 min-w-0 group/xa"
                  >
                    <span class="w-8 h-8 shrink-0 rounded-full overflow-hidden bg-foreground text-white flex items-center justify-center">
                      <img
                        v-if="e.avatar && !failed[`av:${e.key}`]"
                        :src="e.avatar"
                        alt=""
                        width="32"
                        height="32"
                        class="w-full h-auto block"
                        loading="lazy"
                        decoding="async"
                        @error="onImgError(`av:${e.key}`, $event)"
                      />
                      <XGlyph v-else class="w-3.5 h-3.5" />
                    </span>
                    <span class="min-w-0">
                      <span class="block text-[14px] font-semibold text-foreground truncate leading-tight group-hover/xa:underline underline-offset-2">{{ e.name }}</span>
                      <span class="block text-[12px] text-foreground-muted truncate leading-tight">@{{ e.handle }}</span>
                    </span>
                  </a>
                  <span v-else class="text-[14px] font-semibold text-foreground truncate">{{ e.name }}</span>
                  <button
                    v-if="e.kind === 'creator'"
                    class="chip bg-black/[0.05] text-foreground shrink-0 hover:bg-danger/10 hover:text-danger transition-colors"
                    :title="`Unfollow @${e.handle}`"
                    :disabled="removing === e.handle"
                    @click="unfollow(e.handle)"
                  >Creator</button>
                  <span v-if="badge(e)" class="chip bg-black/[0.05] text-foreground shrink-0">{{ badge(e) }}</span>
                  <time
                    v-if="e.post.posted_at"
                    :datetime="e.post.posted_at"
                    :title="fullTime(e.post.posted_at)"
                    class="ml-auto shrink-0 font-mono text-[11px] tracking-[0.03em] text-foreground-muted tabular-nums"
                  >{{ relTime(e.post.posted_at) }}</time>
                  <a
                    v-if="e.post.url"
                    :href="e.post.url"
                    target="_blank"
                    rel="noopener noreferrer"
                    class="shrink-0 w-7 h-7 -mr-1 rounded-full flex items-center justify-center text-foreground/30 hover:text-foreground hover:bg-black/[0.05] transition-colors"
                    aria-label="Open post on X"
                  >
                    <XGlyph class="w-3 h-3" />
                  </a>
                </div>

                <!-- Text -->
                <p
                  v-if="body(e.post)"
                  class="mt-2.5 text-[15px] leading-[1.5] text-foreground whitespace-pre-line break-words [overflow-wrap:anywhere]"
                  :title="e.post.en && e.post.text ? e.post.text : undefined"
                >
                  <template v-for="(tok, k) in tokenize(body(e.post))" :key="k">
                    <span v-if="tok.entity" class="text-info">{{ tok.text }}</span>
                    <template v-else>{{ tok.text }}</template>
                  </template>
                </p>

                <!-- Media: natural ratio always; 2+ images share a 2-col grid -->
                <div
                  v-if="shownMedia(e.post).length"
                  class="mt-3 grid gap-2"
                  :class="shownMedia(e.post).length > 1 ? 'grid-cols-2' : 'grid-cols-1'"
                >
                  <div
                    v-for="(src, i) in shownMedia(e.post)"
                    :key="i"
                    class="rounded-[14px] overflow-hidden bg-fill"
                  >
                    <img
                      :src="src"
                      alt=""
                      class="block w-full h-auto transition-opacity duration-500 [transition-timing-function:var(--ease-out)]"
                      :class="loaded[`${e.post.id}:${i}`] ? 'opacity-100' : 'opacity-0'"
                      loading="lazy"
                      decoding="async"
                      @load="onImgLoad(`${e.post.id}:${i}`, $event)"
                      @error="onImgError(`${e.post.id}:${i}`, $event)"
                    />
                  </div>
                </div>

                <!-- Stats -->
                <div v-if="e.post.stats?.likes != null || e.post.stats?.views != null" class="mt-3 flex items-center gap-3 text-[12px] font-medium text-foreground-muted tabular-nums">
                  <span v-if="e.post.stats.likes != null" class="inline-flex items-center gap-1" :title="`${e.post.stats.likes.toLocaleString()} likes`">
                    <svg width="12" height="12" viewBox="0 0 24 24" fill="currentColor" class="text-accent/80"><path :d="HEART" /></svg>{{ compact(e.post.stats.likes) }}
                  </span>
                  <span v-if="e.post.stats.views != null" :title="`${e.post.stats.views.toLocaleString()} views`">{{ compact(e.post.stats.views) }} views</span>
                </div>
              </article>
            </div>

            <!-- Empty state -->
            <div v-else-if="!(kind === 'creators' && creatorGroups.length)" class="py-20 text-center">
              <p class="text-[17px] font-semibold text-foreground">
                {{ emptyTitle }}
              </p>
              <p class="mt-1.5 text-[14px] text-foreground-muted">
                {{ kind === 'creators'
                  ? 'The bot injects pornographic creators you follow on X (batch JSON).'
                  : 'Inject what you (or an agent) see on x.com.' }}
              </p>
              <button v-if="kind !== 'creators'" class="btn btn-primary mt-6" @click="emit('inject', filter)">
                Inject from X
              </button>
            </div>
          </div>
        </div>
      </div>
    </Transition>
  </Teleport>
</template>

<script setup lang="ts">
import type { CreatorProfile, Star, XPost } from '~/types/api'

const open = defineModel<boolean>('open', { default: false })
const filter = defineModel<string>('filter', { default: '' })
const props = defineProps<{ stars: Star[]; creators?: CreatorProfile[] }>()
const emit = defineEmits<{
  (e: 'inject', code: string): void
  (e: 'creators-changed'): void
}>()

const HEART = 'M12 21.2l-1.4-1.3C5.4 15.4 2 12.3 2 8.5 2 5.4 4.4 3 7.5 3c1.7 0 3.4.8 4.5 2.1C13.1 3.8 14.8 3 16.5 3 19.6 3 22 5.4 22 8.5c0 3.8-3.4 6.9-8.6 11.4L12 21.2z'

/** One feed item: a star's post or a body creator's post. */
interface Entry {
  post: XPost
  kind: 'star' | 'creator'
  /** Unique per author (star code or creator handle) — keys images/badges. */
  key: string
  name: string
  handle: string
  avatar: string
}

type Kind = 'all' | 'stars' | 'creators'

const kind = ref<Kind>('all')

const withPosts = computed(() => props.stars.filter(s => s.x?.posts?.length))
const creatorList = computed(() => props.creators ?? [])
const creatorsWithPosts = computed(() => creatorList.value.filter(c => c.posts?.length))
const filterStar = computed(() => props.stars.find(s => s.code === filter.value) || null)

const kinds = computed<{ id: Kind; label: string; count: number }[]>(() => {
  const out: { id: Kind; label: string; count: number }[] = []
  const hasCreators = creatorList.value.length > 0
  if (hasCreators) {
    out.push({ id: 'all', label: 'All', count: withPosts.value.length + creatorsWithPosts.value.length })
  }
  out.push({ id: 'stars', label: 'Stars', count: withPosts.value.length })
  if (hasCreators) {
    out.push({ id: 'creators', label: 'Porn creators', count: creatorsWithPosts.value.length })
  }
  return out
})

const entries = computed<Entry[]>(() => {
  const out: Entry[] = []
  if (kind.value !== 'creators') {
    for (const s of props.stars) {
      if (filter.value && s.code !== filter.value) continue
      for (const p of s.x?.posts ?? []) {
        out.push({
          post: p, kind: 'star', key: s.code,
          name: s.name, handle: s.x?.handle ?? '', avatar: s.x?.avatar ?? '',
        })
      }
    }
  }
  // Creators scope uses creatorGroups; All merges creator posts into the timeline.
  if (kind.value !== 'stars' && kind.value !== 'creators') {
    for (const c of creatorList.value) {
      for (const p of c.posts ?? []) {
        out.push({
          post: p, kind: 'creator', key: `c:${c.handle}`,
          name: c.name || c.handle, handle: c.handle, avatar: c.avatar,
        })
      }
    }
  }
  out.sort((a, b) => {
    const ta = a.post.posted_at ? Date.parse(a.post.posted_at) : 0
    const tb = b.post.posted_at ? Date.parse(b.post.posted_at) : 0
    return (Number.isNaN(tb) ? 0 : tb) - (Number.isNaN(ta) ? 0 : ta)
  })
  return out
})

interface CreatorGroup {
  handle: string
  name: string
  avatar: string
  entries: Entry[]
}

function postTimeMs(p: XPost): number {
  const t = p.posted_at ? Date.parse(p.posted_at) : 0
  return Number.isNaN(t) ? 0 : t
}

const creatorGroups = computed<CreatorGroup[]>(() => {
  const groups = creatorList.value.map((c) => {
    const entries: Entry[] = (c.posts ?? [])
      .map(p => ({
        post: p,
        kind: 'creator' as const,
        key: `c:${c.handle}`,
        name: c.name || c.handle,
        handle: c.handle,
        avatar: c.avatar,
      }))
      .sort((a, b) => postTimeMs(b.post) - postTimeMs(a.post))
    return {
      handle: c.handle,
      name: c.name || c.handle,
      avatar: c.avatar,
      entries,
      latest: entries.length ? postTimeMs(entries[0].post) : 0,
    }
  })
  return groups
    .filter(g => g.entries.length)
    .sort((a, b) => b.latest - a.latest)
    .map(({ handle, name, avatar, entries }) => ({ handle, name, avatar, entries }))
})

const feedPostCount = computed(() => {
  if (kind.value === 'creators') {
    return creatorGroups.value.reduce((n, g) => n + g.entries.length, 0)
  }
  return entries.value.length
})

const sourceCount = computed(() => {
  if (kind.value === 'creators') return creatorGroups.value.length
  return new Set(entries.value.map(e => e.key)).size
})

const emptyTitle = computed(() => {
  if (kind.value === 'creators') return 'No creator posts yet'
  if (filterStar.value) return `No X posts for ${filterStar.value.name} yet`
  return 'No X posts yet'
})

// A star filter only makes sense in star mode; entering with a star selected
// (the per-star X button) pre-selects that scope.
watch(open, (isOpen) => {
  if (!isOpen) return
  if (filter.value) kind.value = 'stars'
  else if (!kinds.value.some(k => k.id === kind.value)) kind.value = 'all'
})

// Unfollow a body creator: the chip on its cards is the only control, so it
// confirms first (it drops the account and every stored post).
const removing = ref('')
const { unfollowCreator } = useApi()

async function unfollow(handle: string) {
  if (!handle || removing.value) return
  if (!confirm(`Unfollow @${handle} on X?\nIts injected posts are deleted.`)) return
  removing.value = handle
  try {
    await unfollowCreator(handle)
    emit('creators-changed')
  } catch (e: any) {
    alert(e?.data?.detail || e?.message || 'Unfollow failed')
  } finally {
    removing.value = ''
  }
}

const loaded = reactive<Record<string, boolean>>({})
const failed = reactive<Record<string, boolean>>({})

// Images arrive as /api/social/x/media/{key}?u=<original twimg URL>; when the
// local cache cannot serve one, fall back to the original remote URL once.
function origOf(src: string): string | null {
  if (!src.includes('/api/social/x/media/')) return null
  try {
    return new URL(src, globalThis.location?.origin ?? 'http://localhost').searchParams.get('u')
  } catch {
    return null
  }
}

function onImgError(key: string, e: Event) {
  const img = e.target as HTMLImageElement
  const orig = origOf(img.src)
  if (orig && !failed[`${key}:orig`]) {
    failed[`${key}:orig`] = true
    img.src = orig
    return
  }
  failed[key] = true
}

// A truncated response can still fire load; only reveal fully decoded images.
async function onImgLoad(key: string, e: Event) {
  const img = e.target as HTMLImageElement
  try { await img.decode() } catch { onImgError(key, e); return }
  if (!img.naturalWidth) { onImgError(key, e); return }
  loaded[key] = true
}

function shownMedia(p: XPost): string[] {
  return p.media.filter((_, i) => !failed[`${p.id}:${i}`])
}

function body(p: XPost): string {
  return p.en || p.text
}

function badge(e: Entry): string {
  if (e.post.pinned) return 'Pinned'
  if (e.post.author && e.handle && e.post.author.toLowerCase() !== e.handle.toLowerCase()) return 'Repost'
  return ''
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

function fullTime(iso: string): string {
  const t = Date.parse(iso)
  return Number.isNaN(t) ? '' : new Date(t).toLocaleString()
}

function onKeydown(e: KeyboardEvent) {
  if (e.key === 'Escape') open.value = false
}

watch(open, (isOpen) => {
  document.documentElement.style.overflow = isOpen ? 'hidden' : ''
  if (isOpen) document.addEventListener('keydown', onKeydown)
  else document.removeEventListener('keydown', onKeydown)
})

onUnmounted(() => {
  document.documentElement.style.overflow = ''
  document.removeEventListener('keydown', onKeydown)
})
</script>

<style scoped>
.xsocial-enter-active .xs-scrim {
  transition: opacity 0.3s ease;
}
.xsocial-leave-active .xs-scrim {
  transition: opacity 0.2s ease;
}
.xsocial-enter-active .xs-panel {
  transition: transform 0.45s var(--ease-spring), opacity 0.3s var(--ease-spring);
}
.xsocial-leave-active .xs-panel {
  transition: transform 0.22s ease-in, opacity 0.22s ease-in;
}
.xsocial-enter-from .xs-scrim,
.xsocial-leave-to .xs-scrim {
  opacity: 0;
}
.xsocial-enter-from .xs-panel,
.xsocial-leave-to .xs-panel {
  transform: translateY(100%);
}
@media (min-width: 640px) {
  .xsocial-enter-from .xs-panel,
  .xsocial-leave-to .xs-panel {
    transform: scale(0.95);
    opacity: 0;
  }
}
</style>
