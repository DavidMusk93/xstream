<template>
  <span
    class="relative shrink-0 w-10 h-10 rounded-[12px] flex items-center justify-center overflow-hidden"
    :class="toneClass"
  >
    <!-- Image thumbnail: fitted (object-contain), fades in once decoded -->
    <img
      v-if="thumbSrc && !thumbFailed"
      :src="thumbSrc"
      alt=""
      loading="lazy"
      decoding="async"
      class="absolute inset-0 w-full h-full object-contain transition-opacity duration-300"
      :class="thumbReady ? 'opacity-100' : 'opacity-0'"
      @load="onThumbLoad"
      @error="thumbFailed = true"
    />
    <template v-if="!thumbReady">
      <svg v-if="kind === 'dir'" width="17" height="17" viewBox="0 0 24 24" fill="currentColor">
        <path d="M2 6a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2v9a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2z" />
      </svg>
      <svg v-else-if="kind === 'video'" width="14" height="14" viewBox="0 0 24 24" fill="currentColor">
        <path d="M7 4.5v15l12.5-7.5z" />
      </svg>
      <svg v-else-if="kind === 'audio'" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
        <path d="M9 18V5l12-2v13" /><circle cx="6" cy="18" r="3" /><circle cx="18" cy="16" r="3" />
      </svg>
      <svg v-else-if="kind === 'image'" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
        <rect x="3" y="3" width="18" height="18" rx="2" /><circle cx="8.5" cy="8.5" r="1.5" /><polyline points="21 15 16 10 5 21" />
      </svg>
      <svg v-else-if="kind === 'archive'" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
        <path d="M21 8v13H3V8" /><rect x="1" y="3" width="22" height="5" /><line x1="10" y1="12" x2="14" y2="12" />
      </svg>
      <svg v-else-if="kind === 'markdown' || kind === 'text'" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
        <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" /><polyline points="14 2 14 8 20 8" />
        <line x1="8" y1="13" x2="16" y2="13" /><line x1="8" y1="17" x2="13" y2="17" />
      </svg>
      <span v-else class="text-[10px] font-bold tracking-[0.02em] uppercase leading-none">{{ badge }}</span>
    </template>
  </span>
</template>

<script setup lang="ts">
import type { FileKind } from '~/utils/fileKind'

const props = defineProps<{ name: string; path: string; kind: FileKind }>()

const ostore = useOstore()
const thumbSrc = ref('')
const thumbReady = ref(false)
const thumbFailed = ref(false)

const toneClass = computed(() => {
  if (props.kind === 'dir') return 'bg-accent/10 text-accent'
  if (props.kind === 'video') return 'bg-foreground text-white'
  return 'bg-fill text-foreground-muted'
})

/** Short type badge for kinds without a glyph (PDF, JSON, CSV, ZIP...). */
const badge = computed(() => {
  if (props.kind === 'pdf') return 'PDF'
  const ext = fileExt(props.name)
  return ext ? ext.slice(0, 4) : '···'
})

async function onThumbLoad(e: Event) {
  const img = e.target as HTMLImageElement
  try { await img.decode() } catch { /* already decoded or not decodable */ }
  thumbReady.value = true
}

watch(() => props.path, async () => {
  thumbReady.value = false
  thumbFailed.value = false
  thumbSrc.value = ''
  if (props.kind !== 'image') return
  // svg/avif/ico have no server thumbnail; they are small enough to load as-is.
  thumbSrc.value = hasThumb(props.name) ? await ostore.thumbUrl(props.path, 128) : await ostore.fileUrl(props.path)
}, { immediate: true })
</script>
