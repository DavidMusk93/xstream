<template>
  <div class="min-h-screen bg-void">
    <AppHeader>
      <template #leading>
        <NuxtLink to="/" class="btn-icon -ml-1" aria-label="Back to library">
          <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round">
            <polyline points="15 18 9 12 15 6" />
          </svg>
        </NuxtLink>
        <span class="text-[17px] font-semibold text-foreground">Files</span>
      </template>
      <template #actions>
        <label
          class="btn-icon cursor-pointer"
          :class="{ 'opacity-40 pointer-events-none': !configured }"
          data-tip="Upload"
          aria-label="Upload files"
        >
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
            <polyline points="17 8 12 3 7 8" />
            <line x1="12" y1="3" x2="12" y2="15" />
          </svg>
          <input ref="fileInputRef" type="file" multiple class="hidden" @change="onPickFiles" />
        </label>
        <button class="btn-icon" :class="{ 'opacity-40 pointer-events-none': !configured }" data-tip="New folder" aria-label="New folder" @click="openNameSheet('mkdir')">
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z" />
            <line x1="12" y1="11" x2="12" y2="17" />
            <line x1="9" y1="14" x2="15" y2="14" />
          </svg>
        </button>
        <button class="btn-icon" :class="{ 'opacity-40 pointer-events-none': !configured }" data-tip="Refresh" aria-label="Refresh" @click="refresh">
          <svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" :class="{ 'animate-spin': loading }">
            <polyline points="23 4 23 10 17 10" />
            <path d="M20.49 15a9 9 0 1 1-2.12-9.36L23 10" />
          </svg>
        </button>
      </template>
    </AppHeader>

    <main class="pt-[calc(env(safe-area-inset-top)+88px)] pb-32">
      <div class="max-w-5xl mx-auto px-4 sm:px-6">
        <!-- Breadcrumb -->
        <nav v-if="configured" class="px-1 flex items-center flex-wrap gap-1 text-[15px]" aria-label="Path">
          <button
            class="font-semibold transition rounded-md px-1 -mx-1"
            :class="currentPath ? 'text-accent hover:underline' : 'text-foreground'"
            @click="navigateTo('')"
          >Files</button>
          <template v-for="(seg, i) in breadcrumbs" :key="seg.path">
            <span class="text-foreground-muted/40">/</span>
            <button
              class="transition rounded-md px-1 -mx-1 truncate max-w-[40vw]"
              :class="i === breadcrumbs.length - 1 ? 'font-semibold text-foreground' : 'text-accent hover:underline'"
              @click="navigateTo(seg.path)"
            >{{ seg.name }}</button>
          </template>
        </nav>

        <!-- Not configured -->
        <div v-if="!configured" class="mt-8 surface p-10 text-center">
          <div class="inline-flex items-center justify-center w-14 h-14 rounded-full bg-black/[0.05] text-foreground-muted mb-5">
            <svg width="26" height="26" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
              <path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z" />
            </svg>
          </div>
          <p class="text-[19px] font-semibold text-foreground">ostore not configured</p>
          <p class="mt-1.5 text-[15px] text-foreground-muted">The file service is not set up on this server.</p>
        </div>

        <!-- Listing -->
        <div
          v-else
          class="mt-5 transition rounded-[22px]"
          :class="{ 'ring-2 ring-accent ring-offset-2 ring-offset-void': dragOver }"
          @dragover.prevent="dragOver = true"
          @dragleave.prevent="dragOver = false"
          @drop.prevent="onDrop"
        >
          <div v-if="loading && !entries.length" class="surface divide-y divide-black/[0.05] overflow-hidden">
            <div v-for="n in 5" :key="n" class="flex items-center gap-3 px-4 py-3.5">
              <Skeleton class="w-9 h-9 rounded-full shrink-0" />
              <div class="flex-1 space-y-2">
                <Skeleton class="h-3.5 w-1/3 rounded" />
                <Skeleton class="h-3 w-24 rounded" />
              </div>
            </div>
          </div>

          <div v-else-if="errorMsg" class="surface p-10 text-center">
            <p class="text-[17px] font-semibold text-foreground">Couldn't load this folder</p>
            <p class="mt-1.5 text-[15px] text-foreground-muted">{{ errorMsg }}</p>
            <button class="btn btn-secondary mt-6" @click="refresh">Try Again</button>
          </div>

          <div v-else-if="!entries.length" class="surface p-10 text-center">
            <p class="text-[19px] font-semibold text-foreground">Empty folder</p>
            <p class="mt-1.5 text-[15px] text-foreground-muted">Drop files here, or use the upload button.</p>
          </div>

          <div v-else class="surface divide-y divide-black/[0.05] overflow-hidden">
            <div
              v-for="entry in entries"
              :key="entry.path"
              class="flex items-center gap-3 pl-4 pr-1.5 py-3 min-w-0 transition"
              :class="entry.type === 'dir' ? 'cursor-pointer hover:bg-black/[0.03]' : ''"
              @click="entry.type === 'dir' && navigateTo(entry.path)"
            >
              <span
                class="shrink-0 w-9 h-9 rounded-full flex items-center justify-center"
                :class="entry.type === 'dir' ? 'bg-accent/10 text-accent' : 'bg-black/[0.05] text-foreground-muted'"
              >
                <svg v-if="entry.type === 'dir'" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                  <path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z" />
                </svg>
                <svg v-else width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                  <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
                  <polyline points="14 2 14 8 20 8" />
                </svg>
              </span>

              <div class="flex-1 min-w-0">
                <p class="text-[15px] font-medium text-foreground truncate">{{ entry.name }}</p>
                <p class="mt-0.5 text-[12px] text-foreground-muted tabular-nums">
                  <template v-if="entry.type === 'file'">{{ humanSize(entry.size) }}<span class="mx-1.5 text-foreground-muted/40">·</span></template>{{ relTime(entry.mtime) }}
                </p>
              </div>

              <div class="flex items-center gap-0.5 shrink-0" @click.stop>
                <button
                  v-if="isVideo(entry)"
                  class="btn-icon text-accent"
                  data-tip="Play"
                  aria-label="Play"
                  @click="playFile(entry)"
                >
                  <svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor">
                    <path d="M7 4.5v15l12.5-7.5z" />
                  </svg>
                </button>
                <button
                  v-if="entry.type === 'file'"
                  class="btn-icon text-foreground-muted"
                  data-tip="Download"
                  aria-label="Download"
                  @click="downloadFile(entry)"
                >
                  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                    <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
                    <polyline points="7 10 12 15 17 10" />
                    <line x1="12" y1="15" x2="12" y2="3" />
                  </svg>
                </button>
                <button
                  class="btn-icon text-foreground-muted"
                  data-tip="Rename"
                  aria-label="Rename"
                  @click="openNameSheet('rename', entry)"
                >
                  <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                    <path d="M12 20h9" />
                    <path d="M16.5 3.5a2.121 2.121 0 0 1 3 3L7 19l-4 1 1-4L16.5 3.5z" />
                  </svg>
                </button>
                <button
                  class="btn-icon text-foreground-muted"
                  data-tip="Delete"
                  aria-label="Delete"
                  @click="deleteEntry(entry)"
                >
                  <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round">
                    <polyline points="3 6 5 6 21 6" />
                    <path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2" />
                  </svg>
                </button>
              </div>
            </div>
          </div>
        </div>
      </div>
    </main>

    <!-- New folder / rename -->
    <Sheet v-model:open="nameSheetOpen" :title="nameSheetMode === 'mkdir' ? 'New Folder' : 'Rename'" :subtitle="nameSheetMode === 'rename' ? renameTarget?.name : undefined">
      <form @submit.prevent="submitNameSheet">
        <input
          ref="nameInputRef"
          v-model="nameValue"
          type="text"
          spellcheck="false"
          placeholder="Name"
          class="field w-full"
        />
        <p v-if="nameError" class="mt-3 text-[14px] text-danger">{{ nameError }}</p>
        <div class="mt-5 flex justify-end gap-2">
          <button type="button" class="btn btn-secondary" @click="nameSheetOpen = false">Cancel</button>
          <button type="submit" class="btn btn-primary" :disabled="nameSubmitting || !nameValue.trim()">
            <span v-if="nameSubmitting" class="spinner w-4 h-4" />
            <span v-else>{{ nameSheetMode === 'mkdir' ? 'Create' : 'Rename' }}</span>
          </button>
        </div>
      </form>
    </Sheet>

    <FilePlayerModal v-model:open="playerOpen" :path="playerPath" />

    <SyncToast
      :visible="toastVisible"
      :state="toastState"
      :title="toastTitle"
      :detail="toastDetail"
      :progress-text="toastProgressText"
      :fraction="toastFraction"
      @dismiss="dismissToast"
    />
  </div>
</template>

<script setup lang="ts">
import type { OstoreEntry } from '~/types/api'
import { OstoreError } from '~/composables/useOstore'

const VIDEO_EXTS = ['.mp4', '.mkv', '.avi', '.mov', '.wmv', '.flv', '.webm', '.m4v', '.ts']

const { track } = useTrack()
const ostore = useOstore()

const configured = ref(true)
const currentPath = ref('')
const entries = ref<OstoreEntry[]>([])
const loading = ref(false)
const errorMsg = ref('')

const breadcrumbs = computed(() => {
  const parts = currentPath.value.split('/').filter(Boolean)
  return parts.map((name, i) => ({ name, path: parts.slice(0, i + 1).join('/') }))
})

function humanSize(bytes: number): string {
  if (bytes >= 1024 ** 3) return `${(bytes / 1024 ** 3).toFixed(1)} GB`
  if (bytes >= 1024 ** 2) return `${(bytes / 1024 ** 2).toFixed(1)} MB`
  if (bytes >= 1024) return `${(bytes / 1024).toFixed(0)} KB`
  return `${bytes} B`
}

function relTime(mtime: number): string {
  const sec = Math.max(0, Date.now() / 1000 - mtime)
  if (sec < 60) return 'just now'
  if (sec < 3600) return `${Math.floor(sec / 60)}m ago`
  if (sec < 86400) return `${Math.floor(sec / 3600)}h ago`
  if (sec < 30 * 86400) return `${Math.floor(sec / 86400)}d ago`
  return new Date(mtime * 1000).toLocaleDateString()
}

function isVideo(entry: OstoreEntry): boolean {
  if (entry.type !== 'file') return false
  const lower = entry.name.toLowerCase()
  return VIDEO_EXTS.some(ext => lower.endsWith(ext))
}

async function refresh() {
  loading.value = true
  errorMsg.value = ''
  try {
    const res = await ostore.list(currentPath.value)
    entries.value = res.entries
  } catch (e: any) {
    errorMsg.value = e?.message || 'Load failed'
  } finally {
    loading.value = false
  }
}

function navigateTo(path: string) {
  currentPath.value = path
  refresh()
}

// Uploads: one sequential queue feeding a single SyncToast.
const fileInputRef = ref<HTMLInputElement>()
const dragOver = ref(false)
const uploadQueue: File[] = []
let uploadActive = false
let uploadTotalFiles = 0
let uploadDoneFiles = 0

const toastVisible = ref(false)
const toastState = ref<'running' | 'success' | 'error'>('running')
const toastTitle = ref('')
const toastDetail = ref('')
const toastProgressText = ref('')
const toastFraction = ref(0)
let toastTimer: ReturnType<typeof setTimeout> | null = null

function showRunningToast(title: string, progressText = '', fraction = 0.02) {
  if (toastTimer) { clearTimeout(toastTimer); toastTimer = null }
  toastState.value = 'running'
  toastTitle.value = title
  toastDetail.value = ''
  toastProgressText.value = progressText
  toastFraction.value = fraction
  toastVisible.value = true
}

function finishToast(title: string, detail: string, state: 'success' | 'error') {
  toastState.value = state
  toastTitle.value = title
  toastDetail.value = detail
  toastProgressText.value = ''
  toastFraction.value = 1
  toastVisible.value = true
  if (toastTimer) clearTimeout(toastTimer)
  toastTimer = setTimeout(() => { toastVisible.value = false }, state === 'error' ? 6000 : 4000)
}

function dismissToast() {
  toastVisible.value = false
  if (toastTimer) clearTimeout(toastTimer)
}

function onPickFiles(e: Event) {
  const input = e.target as HTMLInputElement
  const files = Array.from(input.files ?? [])
  input.value = ''
  if (files.length) enqueueUpload(files)
}

function onDrop(e: DragEvent) {
  dragOver.value = false
  const files = Array.from(e.dataTransfer?.files ?? [])
  if (files.length) enqueueUpload(files)
}

function enqueueUpload(files: File[]) {
  uploadQueue.push(...files)
  uploadTotalFiles += files.length
  if (!uploadActive) drainUploadQueue()
}

async function drainUploadQueue() {
  if (uploadActive) return
  uploadActive = true
  const dir = currentPath.value

  while (uploadQueue.length) {
    const batch = uploadQueue.splice(0, uploadQueue.length)
    showRunningToast(`Uploading ${batch.length} file${batch.length > 1 ? 's' : ''}`)
    try {
      await ostore.upload(dir, batch, (loaded, total) => {
        toastProgressText.value = `${humanSize(loaded)} / ${humanSize(total)}`
        toastFraction.value = total ? loaded / total : 0.02
      })
      uploadDoneFiles += batch.length
      track('files_upload', { meta: { path: dir, count: batch.length } })
    } catch (e: any) {
      uploadActive = false
      uploadQueue.length = 0
      const msg = e instanceof OstoreError ? e.message : (e?.message || 'Upload failed')
      finishToast('Upload failed', msg, 'error')
      uploadTotalFiles = 0
      uploadDoneFiles = 0
      refresh()
      return
    }
  }

  uploadActive = false
  const n = uploadDoneFiles
  uploadTotalFiles = 0
  uploadDoneFiles = 0
  finishToast(`Uploaded ${n} file${n > 1 ? 's' : ''}`, '', 'success')
  refresh()
}

// New folder / rename sheet.
const nameSheetOpen = ref(false)
const nameSheetMode = ref<'mkdir' | 'rename'>('mkdir')
const renameTarget = ref<OstoreEntry | null>(null)
const nameValue = ref('')
const nameError = ref('')
const nameSubmitting = ref(false)
const nameInputRef = ref<HTMLInputElement>()

function openNameSheet(mode: 'mkdir' | 'rename', entry?: OstoreEntry) {
  nameSheetMode.value = mode
  renameTarget.value = entry ?? null
  nameValue.value = mode === 'rename' ? entry?.name ?? '' : ''
  nameError.value = ''
  nameSheetOpen.value = true
  nextTick(() => nameInputRef.value?.focus())
}

function joinPath(dir: string, name: string): string {
  return dir ? `${dir}/${name}` : name
}

async function submitNameSheet() {
  const name = nameValue.value.trim().replace(/^\/+|\/+$/g, '')
  if (!name) return
  if (name.includes('..')) {
    nameError.value = 'Name must not contain ".."'
    return
  }
  nameSubmitting.value = true
  nameError.value = ''
  try {
    if (nameSheetMode.value === 'mkdir') {
      await ostore.mkdir(joinPath(currentPath.value, name))
    } else if (renameTarget.value) {
      const from = renameTarget.value.path
      const dir = from.split('/').slice(0, -1).join('/')
      await ostore.move(from, joinPath(dir, name))
    }
    nameSheetOpen.value = false
    refresh()
  } catch (e: any) {
    nameError.value = e?.message || 'Operation failed'
  } finally {
    nameSubmitting.value = false
  }
}

// Row actions.
const playerOpen = ref(false)
const playerPath = ref('')

function playFile(entry: OstoreEntry) {
  track('files_play', { meta: { path: entry.path } })
  playerPath.value = entry.path
  playerOpen.value = true
}

async function downloadFile(entry: OstoreEntry) {
  try {
    const url = await ostore.fileUrl(entry.path)
    const a = document.createElement('a')
    a.href = url
    a.download = entry.name
    a.target = '_blank'
    a.rel = 'noopener'
    a.click()
  } catch (e: any) {
    errorMsg.value = e?.message || 'Download failed'
  }
}

async function deleteEntry(entry: OstoreEntry) {
  const recursive = entry.type === 'dir'
  const what = recursive ? `folder "${entry.name}" and everything in it` : `"${entry.name}"`
  if (!confirm(`Delete ${what}?`)) return
  try {
    await ostore.remove(entry.path, recursive)
    track('files_delete', { meta: { path: entry.path, type: entry.type } })
    refresh()
  } catch (e: any) {
    errorMsg.value = e?.message || 'Delete failed'
  }
}

// Live refresh via the ostore SSE stream; throttled to one listing reload
// per second so a busy folder doesn't hammer the API.
let es: EventSource | null = null
let lastSseRefresh = 0
let sseRefreshTimer: ReturnType<typeof setTimeout> | null = null

function throttledRefresh() {
  const now = Date.now()
  const elapsed = now - lastSseRefresh
  if (elapsed >= 1000) {
    lastSseRefresh = now
    refresh()
    return
  }
  if (!sseRefreshTimer) {
    sseRefreshTimer = setTimeout(() => {
      sseRefreshTimer = null
      lastSseRefresh = Date.now()
      refresh()
    }, 1000 - elapsed)
  }
}

onMounted(async () => {
  try {
    await ostore.init()
  } catch (e: any) {
    // 503 = the backend has no ostore configured; anything else also leaves
    // the page on the empty state since every call needs the config.
    configured.value = false
    return
  }
  refresh()
  try {
    es = new EventSource(await ostore.eventsUrl())
    for (const type of ['object.created', 'object.updated', 'object.deleted', 'object.moved', 'object.mkdir']) {
      es.addEventListener(type, throttledRefresh)
    }
  } catch {
    // SSE is best-effort; manual refresh still works.
  }
})

onUnmounted(() => {
  es?.close()
  es = null
  if (sseRefreshTimer) clearTimeout(sseRefreshTimer)
  if (toastTimer) clearTimeout(toastTimer)
})
</script>
