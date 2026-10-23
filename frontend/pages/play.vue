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

    <main class="pt-[calc(env(safe-area-inset-top)+88px)] pb-32">
      <div class="max-w-5xl mx-auto px-4 sm:px-6">
        <!-- Magnet input -->
        <form @submit.prevent="play">
          <div class="surface p-4 sm:p-5">
            <textarea
              v-model="magnet"
              rows="3"
              spellcheck="false"
              placeholder="magnet:?xt=urn:btih:…"
              class="field w-full font-mono text-[13px] leading-relaxed resize-none"
            />
            <div class="mt-3 flex items-center justify-between gap-3">
              <p v-if="errorMsg" class="text-[14px] text-danger leading-snug">{{ errorMsg }}</p>
              <span v-else />
              <button type="submit" class="btn btn-primary shrink-0" :disabled="submitting || !magnet.trim()">
                <span v-if="submitting" class="spinner w-4 h-4" />
                <span v-else>Play</span>
              </button>
            </div>
          </div>
        </form>

        <!-- Recent plays -->
        <section v-if="recents.length || recentsLoaded" class="mt-10">
          <div class="px-1 flex items-baseline justify-between">
            <h2 class="text-[22px] font-bold text-foreground">Recent</h2>
            <span v-if="recents.length" class="text-[14px] text-foreground-muted tabular-nums">{{ recents.length }}</span>
          </div>

          <div v-if="recents.length" class="mt-4 surface divide-y divide-black/[0.05] overflow-hidden">
            <div
              v-for="item in recents"
              :key="item.hash"
              class="flex items-center gap-3 pl-4 pr-1.5 py-3 min-w-0 cursor-pointer transition hover:bg-black/[0.03]"
              @click="reopen(item)"
            >
              <span class="shrink-0 w-9 h-9 rounded-full bg-accent/10 text-accent flex items-center justify-center">
                <MagnetIcon :size="15" />
              </span>
              <div class="flex-1 min-w-0">
                <p class="text-[15px] font-medium text-foreground truncate">
                  {{ item.name || shortHash(item.hash) }}
                </p>
                <p class="mt-0.5 text-[12px] text-foreground-muted tabular-nums">
                  {{ humanSize(item.size_on_disk) }}<span class="mx-1.5 text-foreground-muted/40">·</span>{{ relTime(item.mtime) }}
                </p>
              </div>
              <button
                class="btn-icon shrink-0 text-foreground-muted"
                data-tip="Delete"
                aria-label="Delete"
                @click.stop="removeRecent(item)"
              >
                <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round">
                  <polyline points="3 6 5 6 21 6" />
                  <path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2" />
                </svg>
              </button>
            </div>
          </div>
          <p v-else class="mt-4 px-1 text-[15px] text-foreground-muted">Nothing played yet — paste a magnet above.</p>
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
