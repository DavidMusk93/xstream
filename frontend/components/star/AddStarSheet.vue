<template>
  <Sheet v-model:open="open" title="Follow a Star" subtitle="Paste an ijavtorrent actress page.">
    <form class="space-y-3" @submit.prevent="addStar">
      <input
        ref="inputRef"
        v-model="url"
        type="url"
        inputmode="url"
        autocomplete="off"
        spellcheck="false"
        placeholder="https://ijavtorrent.com/actress/…"
        class="field"
      />
      <button type="submit" class="btn btn-primary w-full h-12" :disabled="adding || !url.trim()">
        <span v-if="adding" class="spinner w-4 h-4" />
        {{ adding ? 'Adding…' : 'Follow' }}
      </button>
    </form>

    <Transition name="fade">
      <p v-if="error" class="mt-3 text-[14px] text-danger">{{ error }}</p>
      <p v-else-if="success" class="mt-3 text-[14px] text-foreground-muted">
        <span class="text-success font-semibold">✓</span> {{ success }}
      </p>
    </Transition>

    <NuxtLink
      to="/search"
      class="mt-5 flex items-center justify-between px-4 h-12 rounded-2xl bg-black/[0.03] text-[14px] text-foreground hover:bg-black/[0.05] transition-colors"
      @click="open = false"
    >
      <span>Don't have a link? <span class="text-foreground-muted">Search by name</span></span>
      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" class="text-foreground-muted">
        <polyline points="9 18 15 12 9 6" />
      </svg>
    </NuxtLink>

    <div v-if="visibleRecent.length" class="mt-7">
      <div class="flex items-center justify-between mb-2.5">
        <h3 class="text-[13px] font-semibold text-foreground-muted">Recently Added</h3>
        <button class="text-[13px] text-foreground-muted hover:text-foreground transition-colors" @click="clearRecent">Clear</button>
      </div>
      <div class="flex flex-wrap gap-2">
        <button
          v-for="s in visibleRecent"
          :key="s.code"
          class="btn btn-sm btn-secondary font-medium"
          @click="jump(s.code)"
        >
          {{ s.name }}
        </button>
      </div>
    </div>
  </Sheet>
</template>

<script setup lang="ts">
import type { Star } from '~/types/api'

interface RecentStar {
  name: string
  code: string
  url: string
  addedAt: number
}

const open = defineModel<boolean>('open', { default: false })
const props = defineProps<{ stars: Star[] }>()
const emit = defineEmits<{
  (e: 'jump', code: string): void
  (e: 'added', payload: { code: string; name: string; handle?: string }): void
}>()

const config = useRuntimeConfig()
const { track } = useTrack()
const { add: addLog } = useEventLog()

const inputRef = ref<HTMLInputElement>()
const url = ref('')
const adding = ref(false)
const error = ref('')
const success = ref('')
const recent = ref<RecentStar[]>([])

// Deleted stars drop out of the list; a just-added star shows up as soon
// as the roster refetch lands.
const visibleRecent = computed(() => {
  const codes = new Set(props.stars.map(s => s.code))
  return recent.value.filter(s => codes.has(s.code))
})

function loadRecent() {
  try {
    const raw = localStorage.getItem('recentStars')
    recent.value = raw ? JSON.parse(raw) : []
  } catch { recent.value = [] }
}

function saveRecent() {
  localStorage.setItem('recentStars', JSON.stringify(recent.value.slice(0, 20)))
}

function clearRecent() {
  recent.value = []
  localStorage.removeItem('recentStars')
}

function jump(code: string) {
  open.value = false
  emit('jump', code)
}

watch(open, (isOpen) => {
  if (!isOpen) return
  loadRecent()
  error.value = ''
  success.value = ''
  nextTick(() => inputRef.value?.focus())
})

async function addStar() {
  const pageUrl = url.value.trim()
  if (!pageUrl || adding.value) return
  error.value = ''
  success.value = ''
  adding.value = true

  try {
    const res = await $fetch('/api/stars/add', {
      baseURL: config.public.apiBase,
      method: 'POST',
      body: { star_page_url: pageUrl },
    }) as any

    const addedCode = res.code as string
    const addedName = res.name as string
    const titlesFound = res.titles_found as number

    success.value = `Following ${addedName} — ${titlesFound} titles found, syncing in background.`
    url.value = ''
    track('add_star', { code: addedCode, meta: { name: addedName, titles_found: titlesFound } })
    addLog({ kind: 'action', title: `Added star ${addedName}`, detail: `${titlesFound} titles found, syncing in background`, state: 'success' })

    recent.value = [
      { name: addedName, code: addedCode, url: res.star_page_url, addedAt: Date.now() },
      ...recent.value.filter(s => s.code !== addedCode),
    ]
    saveRecent()

    emit('added', { code: addedCode, name: addedName, handle: res.handle as string | undefined })
  } catch (e: any) {
    const msg = e?.data?.detail || e?.message || 'Failed to add'
    error.value = msg
    addLog({ kind: 'action', title: 'Add star failed', detail: msg, state: 'error' })
  } finally {
    adding.value = false
  }
}

onMounted(() => {
  const { onServerEvent } = useEventSource()
  const off = onServerEvent('star.ready', (data: any) => {
    if (open.value) success.value = `${data.name} is ready — ${data.titles_count} titles.`
  })
  onUnmounted(off)
})
</script>
