<template>
  <Teleport to="body">
    <Transition name="player" :duration="{ enter: 450, leave: 200 }">
      <div
        v-if="isOpen && entry"
        class="player-root fixed inset-0 z-[100] flex items-center justify-center bg-black/90 backdrop-blur-xl"
        role="dialog"
        aria-modal="true"
        :aria-label="entry.name"
        @click.self="close"
      >
        <div
          class="player-stage hero-stage relative w-full h-full sm:w-[92vw] sm:max-w-6xl sm:h-[86vh] sm:rounded-[22px] overflow-hidden shadow-2xl flex flex-col"
          :class="[docLike ? 'bg-white' : 'bg-black', { 'controls-shown': controlsShown }]"
          @touchstart.passive="onTouchStart"
          @touchend.passive="onTouchEnd"
        >
          <!-- Top bar -->
          <div
            class="z-30 flex items-center gap-3 pl-5 pr-3 pt-[max(12px,env(safe-area-inset-top))] sm:pt-3 pb-3 shrink-0"
            :class="docLike ? 'border-b border-black/[0.06] bg-white' : 'absolute top-0 inset-x-0 pb-10 bg-gradient-to-b from-black/60 to-transparent'"
          >
            <div class="min-w-0 flex-1">
              <p class="text-[15px] font-semibold truncate" :class="docLike ? 'text-foreground' : 'text-white/95'">{{ entry.name }}</p>
              <p class="text-[12px] tabular-nums truncate" :class="docLike ? 'text-foreground-muted' : 'text-white/60'">
                {{ kindLabel(entry.name, kind) }}<span class="mx-1.5 opacity-50">·</span>{{ humanSize(entry.size) }}
              </p>
            </div>
            <button :class="barBtn" title="Download" aria-label="Download" @click="download">
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round">
                <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" /><polyline points="7 10 12 15 17 10" /><line x1="12" y1="15" x2="12" y2="3" />
              </svg>
            </button>
            <button :class="barBtn" aria-label="Close preview" @click="close">
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
                <line x1="18" y1="6" x2="6" y2="18" /><line x1="6" y1="6" x2="18" y2="18" />
              </svg>
            </button>
          </div>

          <!-- Content -->
          <div class="relative flex-1 min-h-0">
            <!-- Image: natural ratio, fitted; visible only once decoded -->
            <div v-if="kind === 'image' && src && !mediaFailed" class="absolute inset-0 flex items-center justify-center p-0 sm:p-6">
              <span v-if="!imageReady" class="spinner w-6 h-6 text-white/60" />
              <img
                :key="src"
                :src="src"
                :alt="entry.name"
                class="max-w-full max-h-full object-contain transition-opacity duration-300 select-none"
                :class="imageReady ? 'opacity-100' : 'opacity-0 absolute'"
                draggable="false"
                @load="onImageLoad"
                @error="mediaFailed = true"
              />
            </div>

            <video
              v-else-if="kind === 'video' && src && !mediaFailed"
              :key="src"
              :src="src"
              controls
              autoplay
              playsinline
              webkit-playsinline
              preload="auto"
              class="absolute inset-0 w-full h-full object-contain"
              @error="mediaFailed = true"
            />

            <div v-else-if="kind === 'audio' && src && !mediaFailed" class="absolute inset-0 flex flex-col items-center justify-center px-6">
              <div class="w-28 h-28 sm:w-36 sm:h-36 rounded-[28px] bg-white/[0.08] text-white/80 flex items-center justify-center">
                <svg width="44" height="44" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round">
                  <path d="M9 18V5l12-2v13" /><circle cx="6" cy="18" r="3" /><circle cx="18" cy="16" r="3" />
                </svg>
              </div>
              <p class="mt-6 max-w-md text-center text-[17px] font-semibold text-white/95 break-words">{{ baseName }}</p>
              <audio :key="src" :src="src" controls autoplay class="mt-6 w-full max-w-md" @error="mediaFailed = true" />
            </div>

            <!-- PDF: the browser's own viewer; <object> falls back to its
                 content where there is none (headless, some mobile browsers) -->
            <object
              v-else-if="kind === 'pdf' && src"
              :key="src"
              :data="src"
              type="application/pdf"
              :aria-label="entry.name"
              class="absolute inset-0 w-full h-full bg-white"
            >
              <div class="h-full flex flex-col items-center justify-center px-6 text-center">
                <div class="w-24 h-24 rounded-[24px] bg-fill text-foreground-muted flex items-center justify-center text-[18px] font-bold">PDF</div>
                <p class="mt-6 text-[19px] font-semibold text-foreground break-words">{{ entry.name }}</p>
                <p class="mt-1 text-[14px] text-foreground-muted">This browser can't show PDFs inline.</p>
                <a class="btn btn-primary mt-7" :href="src" target="_blank" rel="noopener">Open PDF</a>
              </div>
            </object>

            <!-- Text kinds -->
            <div v-else-if="textKind && !textBinary" class="absolute inset-0 overflow-auto overscroll-contain">
              <div v-if="textLoading" class="p-6 space-y-3">
                <Skeleton v-for="n in 8" :key="n" class="h-3.5 rounded" :style="{ width: `${40 + ((n * 37) % 55)}%` }" />
              </div>
              <p v-else-if="textError" class="p-10 text-center text-[15px] text-danger">{{ textError }}</p>
              <template v-else>
                <article v-if="kind === 'markdown'" class="md-prose max-w-3xl mx-auto px-5 sm:px-10 py-8" v-html="markdownHtml" />
                <div v-else-if="kind === 'csv' && csvRows.length" class="min-w-full inline-block">
                  <table class="text-[13px] tabular-nums border-separate border-spacing-0">
                    <thead>
                      <tr>
                        <th v-for="(cell, c) in csvRows[0]" :key="c" class="sticky top-0 bg-fill text-left font-semibold text-foreground px-3 py-2 border-b border-black/[0.06] whitespace-nowrap">{{ cell }}</th>
                      </tr>
                    </thead>
                    <tbody>
                      <tr v-for="(row, r) in csvRows.slice(1)" :key="r" class="even:bg-black/[0.02]">
                        <td v-for="(cell, c) in row" :key="c" class="px-3 py-1.5 text-foreground whitespace-nowrap max-w-[28rem] truncate">{{ cell }}</td>
                      </tr>
                    </tbody>
                  </table>
                </div>
                <div v-else class="code-view font-mono text-[12.5px] leading-[1.6] py-4">
                  <div v-for="(line, i) in codeLines" :key="i" class="flex">
                    <span class="sticky left-0 shrink-0 w-12 pr-3 text-right text-foreground-muted/50 bg-white select-none">{{ i + 1 }}</span>
                    <span class="pr-6 whitespace-pre text-foreground">{{ line || ' ' }}</span>
                  </div>
                </div>
                <p v-if="textTruncated" class="sticky bottom-0 py-2.5 text-center text-[13px] text-foreground-muted bg-white/95 border-t border-black/[0.06]">
                  Showing the first 512 KB · <button class="text-accent font-semibold" @click="download">Download</button> for the full file
                </p>
              </template>
            </div>

            <!-- Fallback card: archives, unknown types, binary text, unplayable media -->
            <div v-else class="absolute inset-0 flex flex-col items-center justify-center px-6 text-center" :class="docLike ? '' : 'text-white'">
              <div class="w-24 h-24 rounded-[24px] flex items-center justify-center text-[18px] font-bold uppercase tracking-[0.02em]" :class="docLike ? 'bg-fill text-foreground-muted' : 'bg-white/[0.08] text-white/80'">
                {{ fileExt(entry.name).slice(0, 4) || '···' }}
              </div>
              <p class="mt-6 max-w-md text-[19px] font-semibold break-words" :class="docLike ? 'text-foreground' : 'text-white/95'">{{ entry.name }}</p>
              <p class="mt-1 text-[14px]" :class="docLike ? 'text-foreground-muted' : 'text-white/60'">
                <template v-if="mediaFailed">This {{ kind }} format can't be played in the browser.</template>
                <template v-else-if="textBinary">This file isn't text.</template>
                <template v-else>{{ kindLabel(entry.name, kind) }} · {{ humanSize(entry.size) }} · No preview</template>
              </p>
              <div class="mt-7 flex items-center gap-2.5">
                <button class="btn btn-primary" @click="download">Download</button>
                <button v-if="kind === 'other' && !textBinary && entry.size > SNIFF_MAX && entry.size <= 8 * 1024 * 1024" class="btn" :class="docLike ? 'btn-secondary' : 'bg-white/10 text-white hover:bg-white/15'" @click="forceText = true">
                  Open as Text
                </button>
              </div>
            </div>
          </div>

          <!-- Stepping (hero-nav language) -->
          <template v-if="files.length > 1">
            <button
              class="hero-nav left-3 sm:left-4 z-30"
              :class="{ 'is-off': index <= 0 }"
              aria-label="Previous file"
              @click="step(-1)"
            >
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"><polyline points="15 18 9 12 15 6" /></svg>
            </button>
            <button
              class="hero-nav right-3 sm:right-4 z-30"
              :class="{ 'is-off': index >= files.length - 1 }"
              aria-label="Next file"
              @click="step(1)"
            >
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"><polyline points="9 18 15 12 9 6" /></svg>
            </button>
            <span class="hero-count z-30">{{ index + 1 }} / {{ files.length }}</span>
          </template>
        </div>
      </div>
    </Transition>
  </Teleport>
</template>

<script setup lang="ts">
import type { OstoreEntry } from '~/types/api'
import type { FileKind } from '~/utils/fileKind'

const isOpen = defineModel<boolean>('open', { default: false })
/** Index into `files` of the file being previewed. */
const index = defineModel<number>('index', { default: 0 })
const props = defineProps<{ files: OstoreEntry[] }>()

const ostore = useOstore()
const SNIFF_MAX = 1024 * 1024

const entry = computed<OstoreEntry | undefined>(() => props.files[index.value])
const forceText = ref(false)
const kind = computed<FileKind>(() => {
  if (!entry.value) return 'other'
  return forceText.value ? 'text' : fileKind(entry.value.name)
})
const textKind = computed(() => isTextKind(kind.value))
const baseName = computed(() => entry.value?.name.replace(/\.[^.]+$/, '') ?? '')

const src = ref('')
const mediaFailed = ref(false)
const imageReady = ref(false)

const textLoading = ref(false)
const textError = ref('')
const textBody = ref('')
const textTruncated = ref(false)
const textBinary = ref(false)

/** Document-style kinds render on a white stage; media on black. */
const docLike = computed(() => (textKind.value && !textBinary.value) || kind.value === 'pdf')
const barBtn = computed(() => docLike.value
  ? 'btn-icon shrink-0 bg-black/[0.04] text-foreground-muted hover:text-foreground'
  : 'w-10 h-10 shrink-0 rounded-full bg-white/[0.12] backdrop-blur-md text-white flex items-center justify-center transition hover:bg-white/20 active:scale-[0.92]')

const markdownHtml = computed(() => (kind.value === 'markdown' ? renderMarkdown(textBody.value) : ''))
const codeLines = computed(() => {
  if (kind.value !== 'text' && kind.value !== 'json') return []
  let body = textBody.value
  if (kind.value === 'json' && !textTruncated.value) {
    try { body = JSON.stringify(JSON.parse(body), null, 2) } catch { /* show as-is (jsonl, invalid) */ }
  }
  return body.replace(/\r\n?/g, '\n').split('\n')
})
const csvRows = computed(() => (kind.value === 'csv' ? parseCsv(textBody.value, entry.value?.name.endsWith('.tsv') ? '\t' : ',') : []))

function parseCsv(text: string, sep: string, maxRows = 2000): string[][] {
  const rows: string[][] = []
  let row: string[] = []
  let cell = ''
  let quoted = false
  for (let i = 0; i < text.length && rows.length < maxRows; i++) {
    const ch = text[i]
    if (quoted) {
      if (ch === '"' && text[i + 1] === '"') { cell += '"'; i++ }
      else if (ch === '"') quoted = false
      else cell += ch
    } else if (ch === '"' && cell === '') quoted = true
    else if (ch === sep) { row.push(cell); cell = '' }
    else if (ch === '\n' || ch === '\r') {
      if (ch === '\r' && text[i + 1] === '\n') i++
      row.push(cell); rows.push(row); row = []; cell = ''
    } else cell += ch
  }
  if ((cell || row.length) && rows.length < maxRows) { row.push(cell); rows.push(row) }
  return rows
}

let loadSeq = 0
async function loadEntry() {
  const seq = ++loadSeq
  src.value = ''
  mediaFailed.value = false
  imageReady.value = false
  textBody.value = ''
  textError.value = ''
  textTruncated.value = false
  textBinary.value = false
  const e = entry.value
  if (!isOpen.value || !e) return
  try {
    if (textKind.value) {
      textLoading.value = true
      const res = await ostore.readText(e.path)
      if (seq !== loadSeq) return
      textBody.value = res.text
      textTruncated.value = res.truncated
      textBinary.value = res.binary
    } else if (['image', 'video', 'audio', 'pdf'].includes(kind.value)) {
      const url = await ostore.fileUrl(e.path)
      if (seq === loadSeq) src.value = url
    } else if (kind.value === 'other' && e.size <= SNIFF_MAX) {
      // Unknown type (README, LICENSE-like names, odd extensions): show it as
      // text when it is text.
      const res = await ostore.readText(e.path, SNIFF_MAX)
      if (seq !== loadSeq) return
      if (!res.binary) forceText.value = true
      else textBinary.value = true
    }
  } catch (err: any) {
    if (seq === loadSeq) textError.value = err?.message || 'Could not load this file'
  } finally {
    if (seq === loadSeq) textLoading.value = false
  }
}

async function onImageLoad(e: Event) {
  try { await (e.target as HTMLImageElement).decode() } catch { /* decoded already */ }
  imageReady.value = true
}

watch(() => entry.value?.path, () => { forceText.value = false })
watch([() => entry.value?.path, isOpen, forceText], loadEntry, { immediate: true })

function step(d: number) {
  const next = index.value + d
  if (next >= 0 && next < props.files.length) index.value = next
}

function close() {
  isOpen.value = false
}

async function download() {
  if (!entry.value) return
  const a = document.createElement('a')
  a.href = await ostore.fileUrl(entry.value.path)
  a.download = entry.value.name
  a.rel = 'noopener'
  a.click()
}

// Keyboard: Esc closes, arrows step (not while a media element has focus,
// where arrows seek).
function onKey(e: KeyboardEvent) {
  if (!isOpen.value) return
  if (e.key === 'Escape') { close(); return }
  const tag = (e.target as HTMLElement | null)?.tagName
  if (tag === 'VIDEO' || tag === 'AUDIO' || tag === 'INPUT') return
  if (e.key === 'ArrowLeft') step(-1)
  else if (e.key === 'ArrowRight') step(1)
}

// Touch: a horizontal swipe steps and reveals the controls briefly.
const controlsShown = ref(false)
let controlsTimer: ReturnType<typeof setTimeout> | null = null
let touchX = 0
let touchY = 0
function onTouchStart(e: TouchEvent) {
  touchX = e.touches[0].clientX
  touchY = e.touches[0].clientY
}
function onTouchEnd(e: TouchEvent) {
  const dx = e.changedTouches[0].clientX - touchX
  const dy = e.changedTouches[0].clientY - touchY
  controlsShown.value = true
  if (controlsTimer) clearTimeout(controlsTimer)
  controlsTimer = setTimeout(() => { controlsShown.value = false }, 1600)
  if (Math.abs(dx) > 60 && Math.abs(dx) > Math.abs(dy) * 1.5 && kind.value !== 'csv' && !(textKind.value && !textBinary.value && kind.value !== 'markdown')) {
    step(dx < 0 ? 1 : -1)
  }
}

watch(isOpen, (open) => {
  document.documentElement.style.overflow = open ? 'hidden' : ''
  if (!open) loadSeq++
})
onMounted(() => window.addEventListener('keydown', onKey))
onUnmounted(() => {
  window.removeEventListener('keydown', onKey)
  document.documentElement.style.overflow = ''
  if (controlsTimer) clearTimeout(controlsTimer)
})
</script>

<style scoped>
.player-enter-active {
  transition: opacity 0.3s ease;
}
.player-enter-active .player-stage {
  transition: transform 0.45s var(--ease-spring), opacity 0.3s var(--ease-spring);
}
.player-leave-active,
.player-leave-active .player-stage {
  transition: opacity 0.2s ease, transform 0.2s ease;
}
.player-enter-from,
.player-leave-to {
  opacity: 0;
}
.player-enter-from .player-stage,
.player-leave-to .player-stage {
  transform: scale(0.96);
}

.md-prose {
  @apply text-[15px] sm:text-[16px] leading-[1.7] text-foreground;
}
.md-prose :deep(h1) { @apply text-[28px] font-bold leading-tight mt-2 mb-4; }
.md-prose :deep(h2) { @apply text-[22px] font-bold leading-snug mt-8 mb-3; }
.md-prose :deep(h3) { @apply text-[18px] font-semibold mt-6 mb-2; }
.md-prose :deep(h4),
.md-prose :deep(h5),
.md-prose :deep(h6) { @apply text-[15px] font-semibold mt-5 mb-2; }
.md-prose :deep(p) { @apply my-3; }
.md-prose :deep(a) { @apply text-accent underline-offset-2 hover:underline; }
.md-prose :deep(ul) { @apply my-3 pl-6 list-disc; }
.md-prose :deep(ol) { @apply my-3 pl-6 list-decimal; }
.md-prose :deep(li) { @apply my-1; }
.md-prose :deep(blockquote) { @apply my-4 pl-4 border-l-2 border-accent/40 text-foreground-muted; }
.md-prose :deep(code) { @apply font-mono text-[0.88em] px-1.5 py-0.5 rounded-md bg-black/[0.05]; }
.md-prose :deep(pre) { @apply my-4 p-4 rounded-2xl bg-fill overflow-x-auto text-[13px] leading-[1.6]; }
.md-prose :deep(pre code) { @apply p-0 bg-transparent; }
.md-prose :deep(hr) { @apply my-8 border-black/[0.06]; }
</style>
