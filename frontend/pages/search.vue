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
      <div class="max-w-6xl mx-auto px-4 sm:px-6">
        <!-- Search field -->
        <div class="relative">
          <div class="pointer-events-none absolute -top-28 left-1/2 -translate-x-1/2 w-[560px] max-w-[110vw] h-[280px] rounded-full bg-[radial-gradient(closest-side,rgba(255,55,95,0.09),transparent)]" aria-hidden="true" />
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
            class="pill-field pl-[52px] pr-[120px] text-[17px] [&::-webkit-search-cancel-button]:hidden"
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
        </div>
        <p v-if="errorMsg" class="mt-3 px-5 text-[14px] text-danger">{{ errorMsg }}</p>

        <!-- Idle -->
        <div v-if="!searched && !loading" class="pt-24 text-center">
          <p class="text-[17px] font-semibold text-foreground">Find something new</p>
          <p class="mt-1.5 text-[15px] text-foreground-muted">Search ijavtorrent and sukebei by code, title, or name.</p>
        </div>

        <!-- Loading skeletons -->
        <div v-else-if="loading" class="mt-10">
          <div class="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
            <div v-for="n in 6" :key="n" class="surface overflow-hidden">
              <Skeleton class="w-full aspect-[3/2] !rounded-none" />
              <div class="p-4 space-y-2.5">
                <Skeleton class="h-5 w-24 rounded" />
                <Skeleton class="h-3.5 w-full rounded" />
                <Skeleton class="h-8 w-40 !rounded-full" />
              </div>
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
          <section v-if="actresses.length" class="mt-9">
            <div class="px-1 flex items-baseline justify-between">
              <h2 class="text-[19px] font-bold text-foreground">Actresses</h2>
              <span class="text-[13px] text-foreground-muted tabular-nums">{{ actresses.length }}</span>
            </div>
            <div class="mt-3 -mx-4 sm:mx-0 flex gap-2.5 overflow-x-auto scrollbar-hide px-4 sm:px-0 pb-2 items-start">
              <div
                v-for="(a, i) in actresses"
                :key="a.url"
                v-reveal="Math.min(i, 5) * 0.04"
                class="surface shrink-0 w-[124px] p-2.5 flex flex-col gap-2.5"
              >
                <!-- Natural aspect ratio, never cropped -->
                <NuxtLink
                  v-if="followedCode(a.url)"
                  :to="`/?star=${followedCode(a.url)}`"
                  class="block group"
                >
                  <div class="rounded-xl overflow-hidden bg-fill relative">
                    <img
                      v-if="a.image && !failedCovers.has(a.url)"
                      :src="a.image"
                      :alt="a.name"
                      referrerpolicy="no-referrer"
                      loading="lazy"
                      decoding="async"
                      class="w-full h-auto block select-none transition-transform duration-300 group-hover:scale-[1.03]"
                      @error="failedCovers.add(a.url)"
                    />
                    <div v-else class="aspect-square flex items-center justify-center text-[24px] font-semibold text-foreground-muted/50">
                      {{ a.name.charAt(0) }}
                    </div>
                  </div>
                  <p class="mt-2.5 px-0.5 text-[13px] font-semibold text-foreground leading-tight line-clamp-2 min-h-[2.3em] group-hover:text-accent transition-colors">{{ a.name }}</p>
                </NuxtLink>
                <button
                  v-else
                  type="button"
                  class="block text-left group"
                  :title="`Search ${a.name}`"
                  @click="searchFor(a.name)"
                >
                  <div class="rounded-xl overflow-hidden bg-fill relative">
                    <img
                      v-if="a.image && !failedCovers.has(a.url)"
                      :src="a.image"
                      :alt="a.name"
                      referrerpolicy="no-referrer"
                      loading="lazy"
                      decoding="async"
                      class="w-full h-auto block select-none transition-transform duration-300 group-hover:scale-[1.03]"
                      @error="failedCovers.add(a.url)"
                    />
                    <div v-else class="aspect-square flex items-center justify-center text-[24px] font-semibold text-foreground-muted/50">
                      {{ a.name.charAt(0) }}
                    </div>
                  </div>
                  <p class="mt-2.5 px-0.5 text-[13px] font-semibold text-foreground leading-tight line-clamp-2 min-h-[2.3em] group-hover:text-accent transition-colors">{{ a.name }}</p>
                </button>
                <NuxtLink
                  v-if="followedCode(a.url)"
                  :to="`/?star=${followedCode(a.url)}`"
                  class="btn btn-sm w-full bg-success/10 text-success hover:bg-success/15"
                >
                  Open
                </NuxtLink>
                <button
                  v-else
                  class="btn btn-sm btn-secondary w-full"
                  :disabled="followingUrls.has(a.url)"
                  @click="follow(null, a)"
                >
                  <span v-if="followingUrls.has(a.url)" class="spinner w-3.5 h-3.5" />
                  Follow
                </button>
              </div>
            </div>
          </section>

          <section v-if="items.length" class="mt-9">
            <div class="px-1 flex items-baseline justify-between">
              <h2 class="text-[19px] font-bold text-foreground">Titles</h2>
              <span class="text-[13px] text-foreground-muted tabular-nums">{{ items.length }} results</span>
            </div>

            <div class="mt-3 grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
              <article
                v-for="(item, i) in items"
                :key="item.code"
                v-reveal="Math.min(i, 5) * 0.04"
                class="surface overflow-hidden flex flex-col transition-shadow duration-300 ease-spring hover:shadow-lg"
              >
                <!-- Cover: natural aspect ratio, never cropped -->
                <div class="relative bg-fill">
                  <div
                    v-if="item.cover_url && !isImgReady(item.code) && !failedCovers.has(item.code)"
                    class="thumb-shimmer absolute inset-0 pointer-events-none"
                    aria-hidden="true"
                  />
                  <img
                    v-if="item.cover_url && !failedCovers.has(item.code)"
                    :ref="(el) => bindImgEl(item.code, el as HTMLImageElement | null)"
                    :src="item.cover_url"
                    :alt="item.code"
                    referrerpolicy="no-referrer"
                    loading="lazy"
                    decoding="async"
                    class="w-full h-auto block select-none transition-opacity duration-300 ease-spring"
                    :class="isImgReady(item.code) ? 'opacity-100' : 'opacity-0'"
                    @load="onImgLoad(item.code, $event)"
                    @error="failedCovers.add(item.code)"
                  />
                  <div v-else class="flex items-center justify-center aspect-[3/2]">
                    <span class="text-[17px] font-semibold text-foreground/40">{{ item.code }}</span>
                  </div>
                  <div class="absolute top-2 left-2 flex flex-wrap gap-1.5">
                    <span v-if="item.in_library" class="chip bg-white/90 backdrop-blur-md text-foreground shadow-sm">
                      <span class="w-1.5 h-1.5 rounded-full bg-success" />In Library
                    </span>
                    <span v-if="item.source === 'sukebei'" class="chip bg-white/90 backdrop-blur-md text-warning shadow-sm">sukebei</span>
                    <span v-if="isHd(item)" class="chip bg-white/90 backdrop-blur-md text-foreground shadow-sm">HD</span>
                  </div>
                </div>

                <div class="p-4 flex flex-col gap-2.5 flex-1">
                  <div class="flex items-baseline justify-between gap-2">
                    <h3 class="text-[19px] font-bold text-foreground leading-tight truncate">{{ item.code }}</h3>
                    <span v-if="item.release_date" class="shrink-0 text-[12px] text-foreground-muted tabular-nums">
                      {{ fmtDate(item.release_date) }}
                    </span>
                  </div>
                  <p v-if="item.title" class="text-[13px] text-foreground-muted leading-snug line-clamp-2">
                    {{ item.title }}
                  </p>
                  <p v-if="item.views != null" class="text-[12px] text-foreground-muted/80 tabular-nums">
                    {{ formatCount(item.views) }} views
                  </p>

                  <!-- Actress: follow, or jump straight to her shelf -->
                  <div v-if="item.stars.length" class="flex flex-wrap gap-1.5">
                    <button
                      v-for="star in item.stars"
                      :key="star.url"
                      class="chip transition-colors"
                      :class="followedCode(star.url)
                        ? 'bg-success/10 text-success hover:bg-success/15'
                        : 'bg-black/[0.05] text-foreground hover:bg-black/[0.08]'"
                      @click="onStarChip(item, star)"
                    >
                      <span v-if="followingUrls.has(star.url)" class="spinner w-3 h-3" />
                      <span v-else-if="followedCode(star.url)">✓</span>
                      <span v-else>+</span>
                      {{ star.name }}
                    </button>
                  </div>

                  <!-- Magnet candidates: tap a chip to copy -->
                  <div v-if="item.magnets?.length" class="mt-auto flex flex-wrap gap-1.5 pt-1">
                    <button
                      v-for="(m, mi) in item.magnets"
                      :key="mi"
                      class="chip font-mono tabular-nums transition-colors active:scale-[0.97]"
                      :class="copiedKey === magnetKey(item, mi)
                        ? 'bg-success text-white'
                        : mi === 0
                          ? 'bg-accent/10 text-accent hover:bg-accent/15'
                          : 'bg-black/[0.05] text-foreground-muted hover:bg-black/[0.08]'"
                      :title="`Copy magnet — ${m.magnet}`"
                      @click="copyMagnet(item, m, magnetKey(item, mi))"
                    >
                      <svg v-if="copiedKey !== magnetKey(item, mi)" width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2">
                        <rect x="9" y="9" width="13" height="13" rx="2" />
                        <path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1" />
                      </svg>
                      <svg v-else width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3">
                        <polyline points="20 6 9 17 4 12" />
                      </svg>
                      {{ m.resolution || 'magnet' }}<template v-if="m.size"> · {{ m.size }}</template><template v-if="m.seeds"> · {{ m.seeds }}S</template>
                    </button>
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
import { decodeThumbImage } from '~/utils/thumbCover'

const config = useRuntimeConfig()
const route = useRoute()
const router = useRouter()
const { track } = useTrack()
const { add: addLog } = useEventLog()

const readyImages = reactive<Record<string, boolean>>({})

function isImgReady(key: string): boolean {
  return !!readyImages[key]
}

async function onImgLoad(key: string, e: Event) {
  const img = e.target as HTMLImageElement
  const ok = await decodeThumbImage(img)
  if (ok || (img.complete && img.naturalWidth > 0)) {
    readyImages[key] = true
  } else {
    failedCovers.value.add(key)
  }
}

function bindImgEl(key: string, el: HTMLImageElement | null) {
  if (!el?.complete || el.naturalWidth <= 0) return
  if (readyImages[key]) return
  void decodeThumbImage(el).then((ok) => {
    if (ok || (el.complete && el.naturalWidth > 0)) {
      readyImages[key] = true
    }
  })
}

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
  if (route.query.q) {
    router.replace({ query: {} })
  }
  inputRef.value?.focus()
}

function searchFor(term: string) {
  query.value = term
  search()
}

onMounted(() => {
  const initial = typeof route.query.q === 'string' ? route.query.q.trim() : ''
  if (initial.length >= 2) {
    query.value = initial
    search()
  } else {
    inputRef.value?.focus()
  }
})

// Followed actresses, keyed by page URL -> library code. The code is what
// lets a chip become a link into the library shelf ("关联跳转"), and is also
// how a second follow of the same actress is prevented client-side.
const followedCodes = ref<Map<string, string>>(new Map())
const followingUrls = ref<Set<string>>(new Set())
const failedCovers = ref<Set<string>>(new Set())

function followedCode(url: string): string {
  return followedCodes.value.get(url) ?? ''
}

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

function rememberFollowed(url: string, code: string) {
  const next = new Map(followedCodes.value)
  next.set(url, code)
  followedCodes.value = next
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
  if (route.query.q !== q) {
    router.replace({ query: { q } })
  }

  try {
    const res = await $fetch<SearchResponse>('/api/search', {
      baseURL: config.public.apiBase,
      params: { q },
    })
    items.value = res.items
    actresses.value = res.actresses ?? []
    lastQuery.value = q
    searched.value = true
    const followed = new Map<string, string>()
    for (const star of [
      ...res.items.flatMap(it => it.stars),
      ...(res.actresses ?? []),
    ]) {
      if (star.followed && star.code) followed.set(star.url, star.code)
    }
    followedCodes.value = followed
    track('search', { meta: { query: q, count: res.count } })
  } catch (e: any) {
    errorMsg.value = e?.data?.detail || e?.message || 'Search failed'
    addLog({ kind: 'action', title: 'Search failed', detail: errorMsg.value, state: 'error' })
  } finally {
    loading.value = false
  }
}

async function follow(item: SearchResultItem | null, star: SearchResultStar) {
  if (followedCode(star.url) || followingUrls.value.has(star.url)) return
  followingUrls.value = new Set([...followingUrls.value, star.url])

  try {
    const res = await $fetch('/api/stars/add', {
      baseURL: config.public.apiBase,
      method: 'POST',
      body: { star_page_url: star.url },
    }) as any

    rememberFollowed(star.url, res.code as string)
    showToast(`Following ${res.name}`, `${res.titles_found} titles found, syncing in background`, 'success')
    track('add_star', { code: res.code, meta: { name: res.name, source: 'search', ...(item ? { via: item.code } : {}) } })
    addLog({ kind: 'action', title: `Followed ${res.name}`, detail: item ? `via search ${item.code}` : 'via search actress match', state: 'success' })
    const { patchStarAdded, refreshLibrary } = useStars()
    patchStarAdded({ name: res.name, code: res.code, handle: res.handle })
    refreshLibrary().catch(() => {})
  } catch (e: any) {
    if (e?.status === 409 || e?.response?.status === 409) {
      // Already followed (stale page state) — re-run the search so the chip
      // picks up her library code and turns into a link.
      showToast('Already followed', 'Refreshing search state', 'success')
      await search()
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

/** Actress chip: jump to her library shelf when followed, else follow her. */
function onStarChip(item: SearchResultItem, star: SearchResultStar) {
  const code = followedCode(star.url)
  if (code) {
    navigateTo(`/?star=${code}`)
    return
  }
  follow(item, star)
}

onUnmounted(() => {
  if (toastTimer) clearTimeout(toastTimer)
  if (copiedTimer) clearTimeout(copiedTimer)
})
</script>
