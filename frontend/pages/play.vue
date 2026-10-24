<template>
  <div class="min-h-screen bg-void">
    <AppHeader>
      <template #leading>
        <NuxtLink to="/" class="btn-icon -ml-1" aria-label="Back to library">
          <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round">
            <polyline points="15 18 9 12 15 6" />
          </svg>
        </NuxtLink>
        <span class="text-[17px] font-semibold text-foreground">Play</span>
      </template>
    </AppHeader>

    <main class="pt-[calc(env(safe-area-inset-top)+104px)] sm:pt-[calc(env(safe-area-inset-top)+120px)] pb-32">
      <div class="max-w-5xl mx-auto px-4 sm:px-6">
        <!-- Large title -->
        <div class="relative mb-8 sm:mb-10 px-1">
          <div class="pointer-events-none absolute -top-40 -left-24 w-[640px] max-w-[120vw] h-[420px] rounded-full bg-[radial-gradient(closest-side,rgba(255,55,95,0.10),transparent)]" aria-hidden="true" />
          <p class="eyebrow rise relative">
            <span class="text-accent">00</span>
            <span>Any magnet</span>
            <span class="h-px w-10 bg-black/10" />
          </p>
          <h1 class="rise relative mt-3 text-[40px] sm:text-[56px] font-bold text-foreground leading-[1.02]" style="--rise-delay: 0.08s">
            Stream
          </h1>
          <p class="rise relative mt-3 text-[15px] sm:text-[17px] text-foreground-muted max-w-[34rem]" style="--rise-delay: 0.12s">
            Paste a magnet link — playback starts while it downloads, only the part you watch.
          </p>
        </div>

        <!-- Magnet field (same pill as Search) -->
        <form class="rise relative" style="--rise-delay: 0.16s" @submit.prevent="play">
          <span class="absolute left-5 top-1/2 -translate-y-1/2 text-foreground-muted pointer-events-none">
            <MagnetIcon :size="17" />
          </span>
          <input
            v-model="magnet"
            type="text"
            name="magnet"
            aria-label="Magnet link"
            enterkeyhint="go"
            autocomplete="off"
            autocapitalize="off"
            spellcheck="false"
            placeholder="magnet:?xt=urn:btih:…"
            class="w-full h-14 pl-[52px] pr-[108px] rounded-full bg-white shadow-card text-[16px] font-mono text-foreground placeholder:font-sans placeholder:text-foreground-muted/70 outline-none border border-transparent focus:border-accent/40 focus:shadow-[0_0_0_4px_rgba(255,55,95,0.10)] transition-[border-color,box-shadow] duration-200"
            @input="errorMsg = ''"
          />
          <div class="absolute right-2 top-1/2 -translate-y-1/2 flex items-center gap-1">
            <button
              v-if="magnet"
              type="button"
              class="w-7 h-7 rounded-full bg-black/[0.08] text-foreground-muted flex items-center justify-center hover:bg-black/[0.12] transition active:scale-[0.9]"
              aria-label="Clear"
              @click="magnet = ''; errorMsg = ''"
            >
              <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="4" stroke-linecap="round">
                <line x1="18" y1="6" x2="6" y2="18" /><line x1="6" y1="6" x2="18" y2="18" />
              </svg>
            </button>
            <button type="submit" class="btn btn-primary h-10 px-4" :disabled="submitting || !magnet.trim()" aria-label="Play">
              <span v-if="submitting" class="spinner w-4 h-4" />
              <template v-else>
                <svg width="13" height="13" viewBox="0 0 24 24" fill="currentColor"><path d="M7 4.5v15l12.5-7.5z" /></svg>
                <span>Play</span>
              </template>
            </button>
          </div>
        </form>
        <p v-if="errorMsg" class="mt-3 px-5 text-[14px] text-danger">{{ errorMsg }}</p>

        <!-- Recent plays -->
        <section v-if="recentsLoaded" class="mt-16 sm:mt-20">
          <div class="mb-4 sm:mb-5 px-1">
            <p class="eyebrow">
              <span class="text-accent">01</span>
              <span class="tabular-nums">{{ recents.length }} played</span>
              <span class="h-px w-10 bg-black/10" />
            </p>
            <h2 class="mt-2 text-[28px] sm:text-[36px] font-bold text-foreground leading-[1.1]">Recent</h2>
          </div>

          <ul v-if="recents.length" class="surface overflow-hidden">
            <li
              v-for="item in recents"
              :key="item.hash"
              class="group/row flex items-center gap-3.5 pl-4 sm:pl-5 pr-2 py-3 min-w-0 border-b border-black/[0.05] last:border-0 cursor-pointer transition-colors duration-200 hover:bg-black/[0.025]"
              @click="reopen(item)"
            >
              <span class="shrink-0 w-10 h-10 rounded-[12px] bg-foreground text-white flex items-center justify-center">
                <svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor"><path d="M7 4.5v15l12.5-7.5z" /></svg>
              </span>
              <div class="flex-1 min-w-0">
                <p class="text-[15px] sm:text-[17px] text-foreground truncate leading-snug">
                  {{ item.name || shortHash(item.hash) }}
                </p>
                <p class="mt-0.5 text-[13px] font-medium text-foreground-muted tabular-nums">
                  {{ humanSize(item.size_on_disk) }} cached<span class="mx-1.5 text-foreground-muted/40">·</span>{{ relTime(item.mtime) }}
                </p>
              </div>
              <button
                class="row-actions btn-icon shrink-0 text-foreground-muted hover:text-danger hover:bg-danger/10"
                title="Delete"
                :aria-label="`Delete ${item.name || item.hash}`"
                @click.stop="removeRecent(item)"
              >
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                  <polyline points="3 6 5 6 21 6" />
                  <path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2" />
                </svg>
              </button>
            </li>
          </ul>
          <p v-else class="px-1 text-[15px] text-foreground-muted">Nothing played yet — paste a magnet above.</p>
        </section>
      </div>
    </main>

    <VideoModal v-model:open="modalOpen" :hash="activeHash" />
  </div>
</template>

<script setup lang="ts">
import type { RecentPlay } from '~/types/api'

const { track } = useTrack()
const { playDirect, listRecentPlays, deleteRecentPlay } = useApi()

const magnet = ref('')
const submitting = ref(false)
const errorMsg = ref('')

const modalOpen = ref(false)
const activeHash = ref('')

const recents = ref<RecentPlay[]>([])
const recentsLoaded = ref(false)

function extractHash(m: string): string | null {
  const match = m.match(/xt=urn:btih:([a-fA-F0-9]{40})/i)
  return match ? match[1].toLowerCase() : null
}

function shortHash(hash: string): string {
  return `btih:${hash.slice(0, 8)}…${hash.slice(-6)}`
}

function humanSize(bytes: number): string {
  if (!bytes) return '0 MB'
  if (bytes >= 1024 ** 3) return `${(bytes / 1024 ** 3).toFixed(1)} GB`
  if (bytes >= 1024 ** 2) return `${(bytes / 1024 ** 2).toFixed(0)} MB`
  return `${Math.max(1, Math.round(bytes / 1024))} KB`
}

function relTime(mtime: number): string {
  const sec = Math.max(0, Date.now() / 1000 - mtime)
  if (sec < 60) return 'just now'
  if (sec < 3600) return `${Math.floor(sec / 60)}m ago`
  if (sec < 86400) return `${Math.floor(sec / 3600)}h ago`
  if (sec < 30 * 86400) return `${Math.floor(sec / 86400)}d ago`
  return new Date(mtime * 1000).toLocaleDateString()
}

async function refreshRecents() {
  try {
    recents.value = await listRecentPlays()
  } catch {
    // A failed refresh keeps the current list; nothing user-actionable here.
  } finally {
    recentsLoaded.value = true
  }
}

async function play() {
  const raw = magnet.value.trim()
  errorMsg.value = ''
  const hash = extractHash(raw)
  if (!hash) {
    errorMsg.value = 'Invalid magnet link — expected a 40-character btih hash.'
    return
  }
  if (submitting.value) return
  submitting.value = true

  try {
    const res = await playDirect(raw)
    track('play_direct', { meta: { hash: res.hash, name: res.name, ready: res.ready } })
    activeHash.value = res.hash.toLowerCase()
    modalOpen.value = true
    refreshRecents()
  } catch (e: any) {
    errorMsg.value = e?.data?.detail || e?.message || 'Failed to start playback'
  } finally {
    submitting.value = false
  }
}

function reopen(item: RecentPlay) {
  track('play_direct', { meta: { hash: item.hash, source: 'recent' } })
  activeHash.value = item.hash
  modalOpen.value = true
}

async function removeRecent(item: RecentPlay) {
  if (!confirm(`Delete ${item.name || shortHash(item.hash)}?`)) return
  try {
    await deleteRecentPlay(item.hash)
    await refreshRecents()
  } catch (e: any) {
    errorMsg.value = e?.data?.detail || e?.message || 'Delete failed'
  }
}

onMounted(refreshRecents)
</script>

<style scoped>
@media (hover: hover) {
  .row-actions {
    opacity: 0;
    transition: opacity 0.2s var(--ease-out), background-color 0.2s, color 0.2s;
  }
  .group\/row:hover .row-actions,
  .row-actions:focus-visible {
    opacity: 1;
  }
}
</style>
