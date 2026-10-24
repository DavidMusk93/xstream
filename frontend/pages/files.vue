<template>
  <div
    class="min-h-screen bg-void"
    @dragenter.prevent="onDragEnter"
    @dragover.prevent
    @dragleave.prevent="onDragLeave"
    @drop.prevent="onDrop"
  >
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
        <button class="btn-icon" :disabled="!configured" title="New folder" aria-label="New folder" @click="openNameSheet('mkdir')">
          <svg width="19" height="19" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z" />
            <line x1="12" y1="11" x2="12" y2="17" />
            <line x1="9" y1="14" x2="15" y2="14" />
          </svg>
        </button>
        <button class="btn btn-sm btn-dark ml-1 sm:ml-2 !px-3 sm:!px-4" :disabled="!configured" title="Upload files" aria-label="Upload files" @click="fileInputRef?.click()">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
            <polyline points="17 8 12 3 7 8" />
            <line x1="12" y1="3" x2="12" y2="15" />
            <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
          </svg>
          <span class="hidden sm:inline">Upload</span>
        </button>
        <input ref="fileInputRef" type="file" multiple class="hidden" name="files" aria-label="Choose files to upload" @change="onPickFiles" />
      </template>
    </AppHeader>

    <main class="pt-[calc(env(safe-area-inset-top)+104px)] sm:pt-[calc(env(safe-area-inset-top)+120px)] pb-32">
      <div class="max-w-5xl mx-auto px-4 sm:px-6">
        <!-- Large title: eyebrow doubles as the breadcrumb -->
        <div class="relative mb-10 sm:mb-14 px-1">
          <div class="pointer-events-none absolute -top-40 -left-24 w-[640px] max-w-[120vw] h-[420px] rounded-full bg-[radial-gradient(closest-side,rgba(255,55,95,0.10),transparent)]" aria-hidden="true" />
          <nav class="eyebrow rise relative flex-wrap gap-y-1" aria-label="Path">
            <span class="text-accent">00</span>
            <button
              class="transition-colors"
              :class="currentPath ? 'hover:text-foreground' : 'text-foreground'"
              @click="navigateTo('')"
            >Files</button>
            <template v-for="(seg, i) in breadcrumbs" :key="seg.path">
              <span class="text-foreground-muted/50">/</span>
              <button
                class="truncate max-w-[40vw] transition-colors"
                :class="i === breadcrumbs.length - 1 ? 'text-foreground' : 'hover:text-foreground'"
                @click="navigateTo(seg.path)"
              >{{ seg.name }}</button>
            </template>
            <span class="h-px w-10 bg-black/10" />
          </nav>
          <h1 class="rise relative mt-3 text-[40px] sm:text-[56px] font-bold text-foreground leading-[1.02] truncate" style="--rise-delay: 0.08s">
            {{ breadcrumbs.length ? breadcrumbs[breadcrumbs.length - 1].name : 'All Files' }}
          </h1>
          <dl
            v-if="configured && !errorMsg"
            class="rise relative mt-8 sm:mt-10 flex divide-x divide-black/[0.08] tabular-nums"
            style="--rise-delay: 0.16s"
          >
            <div v-for="stat in stats" :key="stat.label" class="pr-6 sm:pr-10 pl-6 sm:pl-10 first:pl-0">
              <dt class="sr-only">{{ stat.label }}</dt>
              <dd class="text-[28px] sm:text-[36px] font-semibold text-foreground leading-none tracking-tight">
                <span v-if="!loaded" class="inline-block w-12 h-7 rounded-md bg-black/[0.06] animate-pulse align-middle" />
                <template v-else>{{ stat.value }}</template>
              </dd>
              <dd class="mt-2 text-[13px] text-foreground-muted" aria-hidden="true">{{ stat.label }}</dd>
            </div>
          </dl>
        </div>

        <!-- Not configured -->
        <div v-if="!configured" class="text-center py-24">
          <p class="text-[22px] font-bold text-foreground">File service not set up</p>
          <p class="mt-1.5 text-[15px] text-foreground-muted">ostore is not configured on this server.</p>
        </div>

        <!-- First load -->
        <div v-else-if="!loaded" class="surface overflow-hidden">
          <div v-for="n in 5" :key="n" class="flex items-center gap-3.5 px-4 sm:px-5 py-3.5 border-b border-black/[0.05] last:border-0">
            <Skeleton class="w-10 h-10 rounded-[12px] shrink-0" />
            <div class="flex-1 space-y-2">
              <Skeleton class="h-3.5 w-1/3 rounded" />
              <Skeleton class="h-3 w-24 rounded" />
            </div>
          </div>
        </div>

        <!-- Error -->
        <div v-else-if="errorMsg" class="text-center py-24">
          <div class="inline-flex items-center justify-center w-14 h-14 rounded-full bg-danger/10 text-danger mb-5">
            <svg width="26" height="26" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
              <circle cx="12" cy="12" r="10" />
              <line x1="12" y1="8" x2="12" y2="12" />
              <line x1="12" y1="16" x2="12.01" y2="16" />
            </svg>
          </div>
          <p class="text-[19px] font-semibold text-foreground">Couldn't load this folder</p>
          <p class="mt-1 text-[15px] text-foreground-muted">{{ errorMsg }}</p>
          <button class="btn btn-secondary mt-6" @click="load(currentPath)">Try Again</button>
        </div>

        <!-- Empty -->
        <div v-else-if="!entries.length" class="text-center py-24">
          <p class="text-[22px] font-bold text-foreground">Nothing here yet</p>
          <p class="mt-1.5 text-[15px] text-foreground-muted">Drop videos anywhere on this page, or upload from your device.</p>
          <div class="mt-7 flex items-center justify-center gap-2.5">
            <button class="btn btn-primary" @click="fileInputRef?.click()">Upload</button>
            <button class="btn btn-secondary" @click="openNameSheet('mkdir')">New Folder</button>
          </div>
        </div>

        <!-- Listing -->
        <ul v-else class="surface overflow-hidden" aria-label="Folder contents">
          <li
            v-for="entry in entries"
            :key="entry.path"
            class="group/row flex items-center gap-3.5 pl-4 sm:pl-5 pr-2 py-3 min-w-0 border-b border-black/[0.05] last:border-0 transition-colors duration-200"
            :class="isOpenable(entry) ? 'cursor-pointer hover:bg-black/[0.025]' : ''"
            @click="openEntry(entry)"
          >
            <span
              class="shrink-0 w-10 h-10 rounded-[12px] flex items-center justify-center"
              :class="entry.type === 'dir' ? 'bg-accent/10 text-accent' : isVideo(entry) ? 'bg-foreground text-white' : 'bg-fill text-foreground-muted'"
            >
              <svg v-if="entry.type === 'dir'" width="17" height="17" viewBox="0 0 24 24" fill="currentColor">
                <path d="M2 6a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2v9a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2z" />
              </svg>
              <svg v-else-if="isVideo(entry)" width="14" height="14" viewBox="0 0 24 24" fill="currentColor">
                <path d="M7 4.5v15l12.5-7.5z" />
              </svg>
              <svg v-else width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
                <polyline points="14 2 14 8 20 8" />
              </svg>
            </span>

            <div class="flex-1 min-w-0">
              <p class="text-[15px] sm:text-[17px] text-foreground truncate leading-snug">{{ entry.name }}</p>
              <p class="mt-0.5 text-[13px] font-medium text-foreground-muted tabular-nums">
                <template v-if="entry.type === 'file'">{{ humanSize(entry.size) }}<span class="mx-1.5 text-foreground-muted/40">·</span></template>{{ relTime(entry.mtime) }}
              </p>
            </div>

            <div class="row-actions flex items-center shrink-0" @click.stop>
              <button
                v-if="entry.type === 'file'"
                class="btn-icon text-foreground-muted hover:text-foreground"
                title="Download"
                :aria-label="`Download ${entry.name}`"
                @click="downloadFile(entry)"
              >
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                  <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
                  <polyline points="7 10 12 15 17 10" />
                  <line x1="12" y1="15" x2="12" y2="3" />
                </svg>
              </button>
              <button
                class="btn-icon text-foreground-muted hover:text-foreground"
                title="Rename"
                :aria-label="`Rename ${entry.name}`"
                @click="openNameSheet('rename', entry)"
              >
                <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                  <path d="M12 20h9" />
                  <path d="M16.5 3.5a2.121 2.121 0 0 1 3 3L7 19l-4 1 1-4L16.5 3.5z" />
                </svg>
              </button>
              <button
                class="btn-icon text-foreground-muted hover:text-danger hover:bg-danger/10"
                title="Delete"
                :aria-label="`Delete ${entry.name}`"
                @click="deleteEntry(entry)"
              >
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                  <polyline points="3 6 5 6 21 6" />
                  <path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2" />
                </svg>
              </button>
            </div>
          </li>
        </ul>
      </div>
    </main>

    <!-- Drop target: the whole page -->
    <Transition name="fade">
      <div
        v-if="dragDepth > 0 && configured"
        class="fixed inset-0 z-[80] pointer-events-none flex items-center justify-center bg-void/70"
      >
        <div class="popover px-8 py-7 text-center">
          <div class="mx-auto w-12 h-12 rounded-full bg-accent/10 text-accent flex items-center justify-center">
            <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round">
              <polyline points="17 8 12 3 7 8" />
              <line x1="12" y1="3" x2="12" y2="15" />
              <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
            </svg>
          </div>
          <p class="mt-3 text-[17px] font-semibold text-foreground">Drop to upload</p>
          <p class="mt-0.5 text-[14px] text-foreground-muted">into {{ currentPath ? `/${currentPath}` : 'All Files' }}</p>
        </div>
      </div>
    </Transition>

    <!-- New folder / rename -->
    <Sheet v-model:open="nameSheetOpen" :title="nameSheetMode === 'mkdir' ? 'New Folder' : 'Rename'" :subtitle="nameSheetMode === 'rename' ? renameTarget?.name : undefined">
      <form @submit.prevent="submitNameSheet">
        <input
          ref="nameInputRef"
          v-model="nameValue"
          type="text"
          name="name"
          spellcheck="false"
          placeholder="Name"
          aria-label="Name"
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

/** Payload of the backend's `files.changed` SSE event (ostore bridge). */
interface FilesChange {
  kind: 'created' | 'updated' | 'deleted' | 'moved' | 'mkdir'
  path: string
  type: 'file' | 'dir'
  size?: number
  from?: string
  mtime?: number | null
}

const { track } = useTrack()
const ostore = useOstore()
const { onServerEvent } = useEventSource()
const route = useRoute()
const router = useRouter()

const configured = ref(true)
const currentPath = ref(typeof route.query.path === 'string' ? route.query.path : '')
const entries = ref<OstoreEntry[]>([])
const loaded = ref(false)
const errorMsg = ref('')

const breadcrumbs = computed(() => {
  const parts = currentPath.value.split('/').filter(Boolean)
  return parts.map((name, i) => ({ name, path: parts.slice(0, i + 1).join('/') }))
})

const stats = computed(() => {
  let dirs = 0
  let files = 0
  let bytes = 0
  for (const e of entries.value) {
    if (e.type === 'dir') dirs++
    else { files++; bytes += e.size }
  }
  return [
    { label: 'Folders', value: dirs },
    { label: 'Files', value: files },
    { label: 'Size', value: humanSize(bytes) },
  ]
})

function humanSize(bytes: number): string {
  if (bytes >= 1024 ** 3) return `${(bytes / 1024 ** 3).toFixed(1)} GB`
  if (bytes >= 1024 ** 2) return `${(bytes / 1024 ** 2).toFixed(1)} MB`
  if (bytes >= 1024) return `${(bytes / 1024).toFixed(0)} KB`
  return `${bytes} B`
}

function relTime(mtime: number): string {
  if (!Number.isFinite(mtime)) return ''
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

function isOpenable(entry: OstoreEntry): boolean {
  return entry.type === 'dir' || isVideo(entry)
}

function openEntry(entry: OstoreEntry) {
  if (entry.type === 'dir') navigateTo(entry.path)
  else if (isVideo(entry)) playFile(entry)
}

// Listing. `quiet` reloads (resync after a missed event window) keep the
// rows on screen; keyed rows make an unchanged result a no-op re-render.
let loadSeq = 0
async function load(path: string, quiet = false) {
  const seq = ++loadSeq
  if (!quiet) {
    loaded.value = false
    errorMsg.value = ''
  }
  try {
    const res = await ostore.list(path)
    if (seq !== loadSeq) return
    entries.value = res.entries
    errorMsg.value = ''
  } catch (e: any) {
    if (seq !== loadSeq) return
    if (!quiet) errorMsg.value = e?.message || 'Load failed'
  } finally {
    if (seq === loadSeq) loaded.value = true
  }
}

function navigateTo(path: string) {
  if (path === currentPath.value) return
  router.push({ query: path ? { path } : {} })
}

watch(() => route.query.path, (p) => {
  const path = typeof p === 'string' ? p : ''
  if (path === currentPath.value && loaded.value) return
  currentPath.value = path
  if (configured.value) load(path)
})

// Live updates: apply each `files.changed` to the visible listing in place.
function parentOf(path: string): string {
  const i = path.lastIndexOf('/')
  return i < 0 ? '' : path.slice(0, i)
}

function under(path: string, dir: string): boolean {
  return dir === '' || path.startsWith(`${dir}/`)
}

/** Direct child of `dir` that contains `path` (or is it), else null. */
function childOf(path: string, dir: string): string | null {
  if (!under(path, dir) || path === dir) return null
  const rest = dir ? path.slice(dir.length + 1) : path
  const head = rest.split('/')[0]
  return dir ? `${dir}/${head}` : head
}

function compareEntries(a: OstoreEntry, b: OstoreEntry): number {
  if (a.type !== b.type) return a.type === 'dir' ? -1 : 1
  return a.name < b.name ? -1 : a.name > b.name ? 1 : 0
}

function upsert(entry: OstoreEntry) {
  const list = entries.value.filter(e => e.path !== entry.path)
  const at = list.findIndex(e => compareEntries(entry, e) < 0)
  list.splice(at < 0 ? list.length : at, 0, entry)
  entries.value = list
}

function removeEntry(path: string) {
  if (entries.value.some(e => e.path === path)) {
    entries.value = entries.value.filter(e => e.path !== path)
  }
}

function addFromEvent(ev: FilesChange) {
  const dir = currentPath.value
  const child = childOf(ev.path, dir)
  if (!child) return
  const mtime = ev.mtime ?? Date.now() / 1000
  if (child === ev.path) {
    upsert({ name: ev.path.slice(ev.path.lastIndexOf('/') + 1), path: ev.path, type: ev.type, size: ev.type === 'file' ? ev.size ?? 0 : 0, mtime })
  } else if (!entries.value.some(e => e.path === child)) {
    // Upload into a not-yet-listed subfolder created it implicitly.
    upsert({ name: child.slice(child.lastIndexOf('/') + 1), path: child, type: 'dir', size: 0, mtime })
  }
}

function onFilesChanged(ev: FilesChange) {
  if (!loaded.value || errorMsg.value) return
  const dir = currentPath.value
  // The folder being viewed (or an ancestor) went away or moved.
  if (ev.kind === 'deleted' && dir && (dir === ev.path || under(dir, ev.path))) {
    navigateTo(parentOf(ev.path))
    return
  }
  if (ev.kind === 'moved' && ev.from && dir && (dir === ev.from || under(dir, ev.from))) {
    router.replace({ query: { path: ev.path + dir.slice(ev.from.length) } })
    return
  }
  switch (ev.kind) {
    case 'created':
    case 'updated':
    case 'mkdir':
      addFromEvent(ev)
      break
    case 'deleted':
      if (parentOf(ev.path) === dir) removeEntry(ev.path)
      break
    case 'moved':
      if (ev.from && parentOf(ev.from) === dir) removeEntry(ev.from)
      addFromEvent(ev)
      break
  }
}

function resync() {
  if (configured.value && loaded.value) load(currentPath.value, true)
}

const offFns: (() => void)[] = []

// Uploads: one sequential queue feeding a single SyncToast.
const fileInputRef = ref<HTMLInputElement>()
const dragDepth = ref(0)
const uploadQueue: File[] = []
let uploadActive = false
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

// dragenter/dragleave also fire when crossing child elements; a depth
// counter keeps the overlay steady instead of flickering per child.
function hasFiles(e: DragEvent): boolean {
  return Array.from(e.dataTransfer?.types ?? []).includes('Files')
}

function onDragEnter(e: DragEvent) {
  if (hasFiles(e)) dragDepth.value++
}

function onDragLeave(e: DragEvent) {
  if (hasFiles(e)) dragDepth.value = Math.max(0, dragDepth.value - 1)
}

function onDrop(e: DragEvent) {
  dragDepth.value = 0
  if (!configured.value) return
  const files = Array.from(e.dataTransfer?.files ?? [])
  if (files.length) enqueueUpload(files)
}

function enqueueUpload(files: File[]) {
  uploadQueue.push(...files)
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
      await ostore.upload(dir, batch, (sent, total) => {
        toastProgressText.value = `${humanSize(sent)} / ${humanSize(total)}`
        toastFraction.value = total ? sent / total : 0.02
      })
      uploadDoneFiles += batch.length
      track('files_upload', { meta: { path: dir, count: batch.length } })
    } catch (e: any) {
      uploadActive = false
      uploadQueue.length = 0
      uploadDoneFiles = 0
      const msg = e instanceof OstoreError ? e.message : (e?.message || 'Upload failed')
      finishToast('Upload failed', msg, 'error')
      return
    }
  }

  uploadActive = false
  const n = uploadDoneFiles
  uploadDoneFiles = 0
  finishToast(`Uploaded ${n} file${n > 1 ? 's' : ''}`, '', 'success')
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
      await ostore.move(from, joinPath(parentOf(from), name))
    }
    nameSheetOpen.value = false
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
    a.rel = 'noopener'
    a.click()
  } catch (e: any) {
    finishToast('Download failed', e?.message || '', 'error')
  }
}

async function deleteEntry(entry: OstoreEntry) {
  const recursive = entry.type === 'dir'
  const what = recursive ? `folder "${entry.name}" and everything in it` : `"${entry.name}"`
  if (!confirm(`Delete ${what}?`)) return
  try {
    await ostore.remove(entry.path, recursive)
    track('files_delete', { meta: { path: entry.path, type: entry.type } })
  } catch (e: any) {
    finishToast('Delete failed', e?.message || '', 'error')
  }
}

onMounted(async () => {
  try {
    await ostore.init()
  } catch {
    // 503 = the backend has no ostore configured; anything else also leaves
    // the page on the empty state since every call needs the config.
    configured.value = false
    loaded.value = true
    return
  }
  offFns.push(
    onServerEvent('files.changed', onFilesChanged),
    onServerEvent('files.resync', resync),
    onServerEvent('sync.resync_required', resync),
    onServerEvent('sse.reconnected', resync),
  )
  load(currentPath.value)
})

onUnmounted(() => {
  offFns.forEach(off => off())
  if (toastTimer) clearTimeout(toastTimer)
})
</script>

<style scoped>
/* Row actions: on intent for pointer devices, always visible on touch. */
@media (hover: hover) {
  .row-actions {
    opacity: 0;
    transition: opacity 0.2s var(--ease-out);
  }
  .group\/row:hover .row-actions,
  .row-actions:focus-within {
    opacity: 1;
  }
}
</style>
