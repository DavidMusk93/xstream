<template>
  <div class="min-h-screen bg-void">
    <AppHeader>
      <template #leading>
        <NuxtLink to="/" class="btn-icon -ml-1" aria-label="Back to library">
          <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round">
            <polyline points="15 18 9 12 15 6" />
          </svg>
        </NuxtLink>
        <span class="text-[17px] font-semibold text-foreground">Search</span>
      </template>
    </AppHeader>

    <main class="pt-[calc(env(safe-area-inset-top)+88px)] pb-32">
      <div class="max-w-5xl mx-auto px-4 sm:px-6">
        <!-- Search field -->
        <form class="relative" role="search" @submit.prevent="search">
          <svg class="absolute left-5 top-1/2 -translate-y-1/2 text-foreground-muted pointer-events-none" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round">
            <circle cx="11" cy="11" r="7.5" />
            <line x1="21" y1="21" x2="16.5" y2="16.5" />
          </svg>
          <input
            ref="inputRef"
            v-model="query"
            type="search"
            enterkeyhint="search"
            autocomplete="off"
            spellcheck="false"
            placeholder="Code, keyword, or actress"
            class="w-full h-14 pl-[52px] pr-[120px] rounded-full bg-white shadow-card text-[17px] text-foreground placeholder:text-foreground-muted/70 outline-none border border-transparent focus:border-accent/40 focus:shadow-[0_0_0_4px_rgba(255,55,95,0.10)] transition-[border-color,box-shadow] duration-200 [&::-webkit-search-cancel-button]:hidden"
          />
          <div class="absolute right-2 top-1/2 -translate-y-1/2 flex items-center gap-1">
            <button
              v-if="query"
              type="button"
              class="w-7 h-7 rounded-full bg-black/[0.08] text-foreground-muted flex items-center justify-center hover:bg-black/[0.12] transition active:scale-[0.9]"
              aria-label="Clear"
              @click="clearQuery"
            >
              <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="4" stroke-linecap="round">
                <line x1="18" y1="6" x2="6" y2="18" /><line x1="6" y1="6" x2="18" y2="18" />
              </svg>
            </button>
            <button type="submit" class="btn btn-primary h-10 px-4" :disabled="loading || query.trim().length < 2">
              <span v-if="loading" class="spinner w-4 h-4" />
              <span v-else>Search</span>
            </button>
          </div>
        </form>
        <p v-if="errorMsg" class="mt-3 px-5 text-[14px] text-danger">{{ errorMsg }}</p>

        <!-- Idle -->
        <div v-if="!searched && !loading" class="pt-24 text-center">
          <p class="text-[17px] font-semibold text-foreground">Find something new</p>
          <p class="mt-1.5 text-[15px] text-foreground-muted">Search ijavtorrent and sukebei by code, title, or name.</p>
        </div>

        <!-- Loading skeletons -->
        <div v-else-if="loading" class="mt-10 space-y-5">
          <div v-for="n in 3" :key="n" class="surface flex flex-col sm:flex-row gap-5 sm:gap-8 p-4 sm:p-6">
            <Skeleton class="w-full sm:w-[280px] md:w-[320px] shrink-0 aspect-[3/2] !rounded-[18px]" />
            <div class="flex-1 space-y-3 sm:py-4">
              <Skeleton class="h-4 w-28 rounded" />
              <Skeleton class="h-9 w-40 rounded-lg" />
              <Skeleton class="h-4 w-full rounded" />
              <Skeleton class="h-11 w-56 !rounded-full" />
            </div>
          </div>
        </div>

        <!-- Empty -->
        <div v-else-if="items.length === 0 && actresses.length === 0" class="pt-24 text-center">
          <p class="text-[17px] font-semibold text-foreground">No Results for “{{ lastQuery }}”</p>
          <p class="mt-1.5 text-[15px] text-foreground-muted">Check the spelling or try a title code.</p>
        </div>

        <template v-else>
          <!-- Actress directory matches: always followable, even when the
               video search found nothing for the name -->
          <section v-if="actresses.length" class="mt-10">
            <h2 class="px-1 text-[22px] font-bold text-foreground">Actresses</h2>
            <div class="mt-4 -mx-4 sm:mx-0 flex gap-3 overflow-x-auto scrollbar-hide px-4 sm:px-0 pb-2 items-start">
              <div
                v-for="(a, i) in actresses"
                :key="a.url"
                v-reveal="Math.min(i, 5) * 0.05"
                class="surface shrink-0 w-[148px] p-3 flex flex-col gap-3"
              >
                <!-- Natural aspect ratio, never cropped -->
                <div class="rounded-2xl overflow-hidden bg-fill">
                  <img
                    v-if="a.image && !failedCovers.has(a.url)"
                    :src="a.image"
                    :alt="a.name"
                    referrerpolicy="no-referrer"
                    loading="lazy"
                    decoding="async"
                    class="w-full h-auto block"
                    @error="failedCovers.add(a.url)"
                  />
                  <div v-else class="aspect-square flex items-center justify-center text-[28px] font-semibold text-foreground-muted/50">
                    {{ a.name.charAt(0) }}
                  </div>
                </div>
                <p class="px-1 text-[14px] font-semibold text-foreground leading-tight line-clamp-2">{{ a.name }}</p>
                <button
                  class="btn btn-sm w-full"
                  :class="isFollowed(a.url) ? 'bg-success/10 text-success disabled:!opacity-100' : 'btn-secondary'"
                  :disabled="isFollowed(a.url) || followingUrls.has(a.url)"
                  @click="follow(null, a)"
                >
                  <span v-if="followingUrls.has(a.url)" class="spinner w-3.5 h-3.5" />
                  {{ isFollowed(a.url) ? 'Following' : 'Follow' }}
                </button>
              </div>
            </div>
          </section>

          <section v-if="items.length" class="mt-10">
            <div class="px-1 flex items-baseline justify-between">
              <h2 class="text-[22px] font-bold text-foreground">Titles</h2>
              <span class="text-[14px] text-foreground-muted tabular-nums">{{ items.length }} results</span>
            </div>

            <div class="mt-4 space-y-5">
              <article
                v-for="(item, i) in items"
                :key="item.code"
                v-reveal="Math.min(i, 3) * 0.06"
                class="surface flex flex-col sm:flex-row gap-5 sm:gap-8 p-4 sm:p-6"
              >
                <!-- Cover: natural aspect ratio, never cropped -->
                <div class="relative w-full sm:w-[280px] md:w-[320px] shrink-0 self-start rounded-[18px] overflow-hidden bg-fill">
                  <img
                    v-if="item.cover_url && !failedCovers.has(item.code)"
                    :src="item.cover_url"
                    :alt="item.code"
                    referrerpolicy="no-referrer"
                    loading="lazy"
                    decoding="async"
                    class="w-full h-auto block"
                    @error="failedCovers.add(item.code)"
                  />
                  <div v-else class="flex flex-col items-center justify-center p-6 text-center aspect-[3/2]">
                    <span class="text-[19px] font-semibold text-foreground/50">{{ item.code }}</span>
                  </div>
                  <span
                    v-if="item.in_library"
                    class="absolute top-2.5 left-2.5 chip bg-white/90 backdrop-blur-md text-foreground shadow-sm"
                  >
                    <span class="w-1.5 h-1.5 rounded-full bg-success" />In Library
                  </span>
                </div>

                <div class="flex-1 min-w-0 flex flex-col justify-center">
                  <div class="flex items-center flex-wrap gap-x-2 gap-y-1 text-[13px] font-medium text-foreground-muted tabular-nums">
                    <span v-if="item.release_date">{{ fmtDate(item.release_date) }}</span>
                    <template v-if="item.views != null">
                      <span v-if="item.release_date" class="text-foreground-muted/40">·</span>
                      <span>{{ formatCount(item.views) }} views</span>
                    </template>
                    <span v-if="isHd(item)" class="chip bg-black/[0.06] text-foreground">HD</span>
                    <span v-if="item.source === 'sukebei'" class="chip bg-warning/10 text-warning">sukebei</span>
                  </div>
                  <h3 class="mt-2 text-[28px] sm:text-[34px] font-bold text-foreground leading-[1.05]">
                    {{ item.code }}
                  </h3>
                  <p v-if="item.title" class="mt-2.5 text-[15px] text-foreground-muted leading-relaxed line-clamp-2">
                    {{ item.title }}
                  </p>

                  <div class="flex items-center gap-2 mt-5 flex-wrap">
                    <button
                      v-if="bestMagnet(item)"
                      class="action w-11 h-11 text-white shadow-[0_6px_20px_-6px_rgba(255,55,95,0.6)] hover:-translate-y-0.5"
                      :class="copiedKey === item.code ? 'bg-success shadow-none' : 'bg-accent hover:bg-accent-hover'"
                      :data-tip="copiedKey === item.code ? 'Copied' : 'Copy best magnet'"
                      :data-tip-show="copiedKey === item.code || undefined"
                      aria-label="Copy best magnet"
                      @click="copyMagnet(item, bestMagnet(item)!, item.code)"
                    >
                      <Transition name="icon-swap" mode="out-in">
                        <MagnetIcon v-if="copiedKey !== item.code" key="copy" :size="18" />
                        <svg v-else key="done" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.8" stroke-linecap="round" stroke-linejoin="round">
                          <polyline points="20 6 9 17 4 12" />
                        </svg>
                      </Transition>
                    </button>

                    <button
                      v-for="star in item.stars"
                      :key="star.url"
                      class="btn"
                      :class="isFollowed(star.url) ? 'bg-success/10 text-success disabled:!opacity-100' : 'btn-secondary'"
                      :disabled="isFollowed(star.url) || followingUrls.has(star.url)"
                      @click="follow(item, star)"
                    >
                      <span v-if="followingUrls.has(star.url)" class="spinner w-3.5 h-3.5" />
                      <svg v-else-if="isFollowed(star.url)" width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round" stroke-linejoin="round">
                        <polyline points="20 6 9 17 4 12" />
                      </svg>
                      <svg v-else width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round">
                        <line x1="12" y1="5" x2="12" y2="19" />
                        <line x1="5" y1="12" x2="19" y2="12" />
                      </svg>
                      {{ star.name }}
                    </button>
                  </div>
                  <p v-if="!item.stars.length" class="mt-2.5 text-[12px] text-foreground-muted">
                    No actress info from this source — search the name to follow.
                  </p>

                  <!-- Magnet candidates as an inset grouped list -->
                  <div
                    v-if="item.magnets?.length"
                    class="mt-5 rounded-2xl bg-black/[0.03] divide-y divide-black/[0.05] overflow-hidden"
                  >
                    <div
                      v-for="(m, i) in item.magnets"
                      :key="i"
                      class="flex items-center gap-2.5 h-11 pl-4 pr-1.5 text-[13px] min-w-0"
                    >
                      <span v-if="m.resolution" class="shrink-0 font-semibold text-foreground">{{ m.resolution }}</span>
                      <span v-if="m.size" class="shrink-0 text-foreground-muted tabular-nums">{{ m.size }}</span>
                      <span v-if="m.seeds" class="shrink-0 text-foreground-muted tabular-nums">{{ m.seeds }} seeds</span>
                      <span class="flex-1 min-w-0 truncate font-mono text-[11px] text-foreground-muted/50">{{ shortHash(m.magnet) }}</span>
                      <button
                        class="shrink-0 w-8 h-8 rounded-full flex items-center justify-center transition active:scale-[0.9]"
                        :class="copiedKey === magnetKey(item, i)
                          ? 'bg-success text-white'
                          : 'text-foreground-muted hover:bg-black/[0.06] hover:text-foreground'"
                        title="Copy magnet"
                        @click="copyMagnet(item, m, magnetKey(item, i))"
                      >
                        <svg v-if="copiedKey !== magnetKey(item, i)" width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2">
                          <rect x="9" y="9" width="13" height="13" rx="2" />
                          <path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1" />
                        </svg>
                        <svg v-else width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3">
                          <polyline points="20 6 9 17 4 12" />
                        </svg>
                      </button>
                    </div>
                  </div>
                </div>
              </article>
            </div>
          </section>
        </template>
      </div>
    </main>

    <!-- Follow feedback toast -->
    <SyncToast
      :visible="toastVisible"
      :state="toastState"
      :title="toastTitle"
      :detail="toastDetail"
      :fraction="1"
      @dismiss="toastVisible = false"
    />
  </div>
</template>

<script setup lang="ts">
import type { SearchResponse, SearchResultActress, SearchResultItem, SearchResultMagnet, SearchResultStar } from '~/types/api'

const config = useRuntimeConfig()
const { track } = useTrack()
const { add: addLog } = useEventLog()

const query = ref('')
const lastQuery = ref('')
const items = ref<SearchResultItem[]>([])
const actresses = ref<SearchResultActress[]>([])
const loading = ref(false)
const searched = ref(false)
const errorMsg = ref('')
const inputRef = ref<HTMLInputElement>()

function clearQuery() {
  query.value = ''
  inputRef.value?.focus()
}

onMounted(() => inputRef.value?.focus())

// Local follow state: server-reported `followed` plus optimistic updates,
// so a follow reflects on every card of the same actress immediately.
const followedUrls = ref<Set<string>>(new Set())
const followingUrls = ref<Set<string>>(new Set())
const failedCovers = ref<Set<string>>(new Set())

const copiedKey = ref('')
let copiedTimer: ReturnType<typeof setTimeout> | null = null

const toastVisible = ref(false)
const toastState = ref<'running' | 'success' | 'error'>('success')
const toastTitle = ref('')
const toastDetail = ref('')
let toastTimer: ReturnType<typeof setTimeout> | null = null

function showToast(title: string, detail: string, state: 'success' | 'error') {
  toastState.value = state
  toastTitle.value = title
  toastDetail.value = detail
  toastVisible.value = true
  if (toastTimer) clearTimeout(toastTimer)
  toastTimer = setTimeout(() => { toastVisible.value = false }, state === 'error' ? 6000 : 4000)
}

function isFollowed(url: string) {
  return followedUrls.value.has(url)
}

function formatCount(n: number) {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}k`
  return String(n)
}

function fmtDate(dateStr?: string | null): string {
  if (!dateStr) return ''
  const parts = dateStr.split('/')
  if (parts.length === 3) {
    return `${parts[2]}-${parts[1].padStart(2, '0')}-${parts[0].padStart(2, '0')}`
  }
  return dateStr
}

function bestMagnet(item: SearchResultItem): SearchResultMagnet | undefined {
  return item.magnets?.[0]
}

function isHd(item: SearchResultItem): boolean {
  const res = bestMagnet(item)?.resolution?.toLowerCase() ?? item.resolution?.toLowerCase() ?? ''
  return res.includes('1080') || res.includes('4k') || res.includes('fhd')
}

function magnetKey(item: SearchResultItem, i: number) {
  return `${item.code}:${i}`
}

function shortHash(magnet: string): string {
  const m = magnet.match(/xt=urn:btih:([0-9a-fA-F]{40})/)
  return m ? `btih:${m[1].toLowerCase()}` : magnet
}

function copyMagnet(item: SearchResultItem, m: SearchResultMagnet, key: string) {
  navigator.clipboard.writeText(m.magnet).then(() => {
    copiedKey.value = key
    if (copiedTimer) clearTimeout(copiedTimer)
    copiedTimer = setTimeout(() => { copiedKey.value = '' }, 1500)
    track('copy_magnet', { code: item.code, meta: { source: 'search' } })
  }).catch(() => {
    // ignore
  })
}

async function search() {
  const q = query.value.trim()
  if (q.length < 2 || loading.value) return
  loading.value = true
  errorMsg.value = ''
  failedCovers.value = new Set()

  try {
    const res = await $fetch<SearchResponse>('/api/search', {
      baseURL: config.public.apiBase,
      params: { q },
    })
    items.value = res.items
    actresses.value = res.actresses ?? []
    lastQuery.value = q
    searched.value = true
    followedUrls.value = new Set([
      ...res.items.flatMap(it => it.stars).filter(s => s.followed).map(s => s.url),
      ...(res.actresses ?? []).filter(a => a.followed).map(a => a.url),
    ])
    track('search', { meta: { query: q, count: res.count } })
  } catch (e: any) {
    errorMsg.value = e?.data?.detail || e?.message || 'Search failed'
    addLog({ kind: 'action', title: 'Search failed', detail: errorMsg.value, state: 'error' })
  } finally {
    loading.value = false
  }
}

async function follow(item: SearchResultItem | null, star: SearchResultStar) {
  if (isFollowed(star.url) || followingUrls.value.has(star.url)) return
  followingUrls.value = new Set([...followingUrls.value, star.url])

  try {
    const res = await $fetch('/api/stars/add', {
      baseURL: config.public.apiBase,
      method: 'POST',
      body: { star_page_url: star.url },
    }) as any

    followedUrls.value = new Set([...followedUrls.value, star.url])
    showToast(`Following ${res.name}`, `${res.titles_found} titles found, syncing in background`, 'success')
    track('add_star', { code: res.code, meta: { name: res.name, source: 'search', ...(item ? { via: item.code } : {}) } })
    addLog({ kind: 'action', title: `Followed ${res.name}`, detail: item ? `via search ${item.code}` : 'via search actress match', state: 'success' })
    const { patchStarAdded, refreshLibrary } = useStars()
    patchStarAdded({ name: res.name, code: res.code, handle: res.handle })
    refreshLibrary().catch(() => {})
  } catch (e: any) {
    if (e?.status === 409 || e?.response?.status === 409) {
      // Already followed — treat as success state
      followedUrls.value = new Set([...followedUrls.value, star.url])
    } else {
      const msg = e?.data?.detail || e?.message || 'Follow failed'
      showToast('Follow failed', msg, 'error')
      addLog({ kind: 'action', title: 'Follow failed', detail: msg, state: 'error' })
    }
  } finally {
    const next = new Set(followingUrls.value)
    next.delete(star.url)
    followingUrls.value = next
  }
}

onUnmounted(() => {
  if (toastTimer) clearTimeout(toastTimer)
  if (copiedTimer) clearTimeout(copiedTimer)
})
</script>
