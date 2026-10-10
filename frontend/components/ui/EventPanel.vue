<template>
  <div ref="rootRef" class="sm:relative">
    <button
      class="btn-icon relative"
      :class="open ? 'bg-black/[0.06]' : ''"
      title="Activity"
      aria-label="Activity"
      :aria-expanded="open"
      @click="toggle"
    >
      <svg width="19" height="19" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
        <polyline points="22 12 18 12 15 21 9 3 6 12 2 12" />
      </svg>
      <span
        v-if="errorCount > 0"
        class="absolute top-1 right-0.5 min-w-[16px] h-4 px-1 rounded-full bg-danger ring-2 ring-white text-white text-[10px] font-bold leading-4 text-center tabular-nums"
      >{{ errorCount > 99 ? '99+' : errorCount }}</span>
      <span
        v-else-if="syncRunning"
        class="absolute top-2 right-2 w-2 h-2 rounded-full bg-info ring-2 ring-white animate-pulse"
      />
    </button>

    <Transition name="pop">
      <div
        v-if="open"
        class="popover fixed sm:absolute left-3 right-3 sm:left-auto sm:right-0 top-[calc(env(safe-area-inset-top)+60px)] sm:top-full sm:mt-2 sm:w-[400px] max-h-[calc(100dvh-84px)] origin-top-right overflow-hidden flex flex-col z-50"
      >
        <div class="px-5 pt-5 pb-4">
          <h3 class="text-[17px] font-semibold text-foreground">Activity</h3>
          <dl class="mt-3 grid grid-cols-2 gap-2">
            <div class="px-3.5 py-2.5 rounded-2xl bg-black/[0.035]">
              <dt class="text-[12px] text-foreground-muted">Last sync</dt>
              <dd class="mt-0.5 text-[14px] font-medium text-foreground truncate tabular-nums">{{ lastRunText }}</dd>
            </div>
            <div class="px-3.5 py-2.5 rounded-2xl bg-black/[0.035]">
              <dt class="text-[12px] text-foreground-muted">Next scheduled</dt>
              <dd class="mt-0.5 text-[14px] font-medium text-foreground tabular-nums">{{ nextRunText }}</dd>
            </div>
          </dl>
          <p v-if="lastRun" class="mt-2.5 text-[12px] text-foreground-muted line-clamp-2">
            <span :class="lastRun.status === 'success' ? 'text-success' : 'text-danger'" class="font-semibold">
              {{ lastRun.status === 'success' ? 'Succeeded' : 'Failed' }}
            </span>
            · {{ lastRun.trigger }}
            <template v-if="lastRun.status === 'success'">
              · +{{ lastRun.total_new }} new, {{ lastRun.total_updated }} updated<span v-if="lastRun.failed_count">, {{ lastRun.failed_count }} failed</span>
            </template>
            <template v-else-if="lastRun.error"> · {{ lastRun.error }}</template>
          </p>
        </div>

        <div class="flex-1 overflow-y-auto min-h-0 px-2 pb-2 border-t border-black/[0.05]">
          <div v-if="entries.length === 0" class="py-14 text-center text-[13px] text-foreground-muted">
            No activity this session
          </div>
          <div
            v-for="(e, i) in entries"
            :key="e.ts + '-' + i"
            class="flex items-start gap-3 px-3 py-2.5 mt-1 rounded-2xl hover:bg-black/[0.03] transition-colors"
          >
            <span
              class="mt-[7px] w-1.5 h-1.5 rounded-full shrink-0"
              :class="{
                'bg-success': e.state === 'success',
                'bg-danger': e.state === 'error',
                'bg-info animate-pulse': e.state === 'running',
                'bg-black/25': !e.state || e.state === 'info',
              }"
            />
            <div class="flex-1 min-w-0">
              <div class="text-[14px] text-foreground leading-snug">{{ e.title }}</div>
              <div v-if="e.detail" class="mt-0.5 text-[12px] text-foreground-muted leading-snug break-words">{{ e.detail }}</div>
            </div>
            <span class="text-[11px] text-foreground-muted/70 tabular-nums shrink-0 mt-0.5">{{ fmtTime(e.ts) }}</span>
          </div>
        </div>
      </div>
    </Transition>
  </div>
</template>

<script setup lang="ts">
interface SyncRun {
  id: number
  trigger: string
  status: string
  started_at?: string
  finished_at?: string
  total_new: number
  total_updated: number
  failed_count: number
  error?: string
}

const open = ref(false)
const rootRef = ref<HTMLElement | null>(null)
useDismiss(rootRef, open)
const { entries } = useEventLog()

const errorCount = computed(() => entries.value.filter(e => e.state === 'error').length)

const syncRunning = ref(false)
const lastRun = ref<SyncRun | null>(null)
const nextScheduledAt = ref<number | null>(null)
const intervalHours = ref(6)

const lastRunText = computed(() => {
  if (syncRunning.value) return 'Running…'
  const finished = lastRun.value?.finished_at
  if (!finished) return 'Never'
  const ts = Date.parse(finished)
  if (Number.isNaN(ts)) return finished
  const mins = Math.max(0, Math.round((Date.now() - ts) / 60000))
  if (mins < 1) return 'Just now'
  if (mins < 60) return `${mins} min ago`
  if (mins < 60 * 24) return `${(mins / 60).toFixed(1)}h ago`
  return new Date(ts).toLocaleDateString(undefined, { month: 'short', day: 'numeric' })
})

const nextRunText = computed(() => {
  if (!nextScheduledAt.value) return '—'
  const mins = Math.max(0, Math.round((nextScheduledAt.value * 1000 - Date.now()) / 60000))
  if (mins >= 60) return `in ${(mins / 60).toFixed(1)}h`
  return `in ${mins} min`
})

async function fetchSyncStatus() {
  try {
    const config = useRuntimeConfig()
    const data = await $fetch<any>('/api/stars/sync', { baseURL: config.public.apiBase })
    syncRunning.value = !!data.running
    lastRun.value = data.last_run ?? null
    nextScheduledAt.value = data.next_scheduled_at ?? null
    intervalHours.value = data.sync_interval_hours ?? 6
  } catch {
    // panel is best-effort
  }
}

function toggle() {
  open.value = !open.value
  if (open.value) fetchSyncStatus()
}

function fmtTime(ts: number): string {
  const d = new Date(ts)
  return `${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}:${String(d.getSeconds()).padStart(2, '0')}`
}

const { add } = useEventLog()
const unsubs: (() => void)[] = []

onMounted(() => {
  fetchSyncStatus()

  // Live sync events → panel entries
  unsubs.push(onServerEvent('sync.started', (d: any) => {
    syncRunning.value = true
    add({ kind: 'sync', title: `Sync started (${d?.trigger ?? 'manual'})`, state: 'running' })
  }))
  unsubs.push(onServerEvent('sync.completed', (d: any) => {
    syncRunning.value = false
    fetchSyncStatus()
    add({
      kind: 'sync',
      title: `Sync completed — +${d?.total_new ?? 0} new`,
      detail: `elapsed ${d?.elapsed ?? '?'}s${d?.failed?.length ? `, failed: ${d.failed.join(', ')}` : ''}`,
      state: d?.failed?.length ? 'info' : 'success',
    })
  }))
  unsubs.push(onServerEvent('sync.error', (d: any) => {
    syncRunning.value = false
    fetchSyncStatus()
    add({ kind: 'sync', title: 'Sync failed', detail: d?.error, state: 'error' })
  }))
  unsubs.push(onServerEvent('star.ready', (d: any) => {
    add({ kind: 'info', title: `Star ready: ${d?.name ?? d?.code}`, detail: `${d?.titles_count ?? 0} titles`, state: 'success' })
  }))

  // Page errors → panel
  const onError = (ev: ErrorEvent) => {
    add({ kind: 'error', title: 'Page error', detail: ev.message, state: 'error' })
  }
  const onRejection = (ev: PromiseRejectionEvent) => {
    add({ kind: 'error', title: 'Unhandled rejection', detail: String(ev.reason).slice(0, 200), state: 'error' })
  }
  window.addEventListener('error', onError)
  window.addEventListener('unhandledrejection', onRejection)
  unsubs.push(() => {
    window.removeEventListener('error', onError)
    window.removeEventListener('unhandledrejection', onRejection)
  })
})

onUnmounted(() => {
  unsubs.forEach(fn => fn())
})
</script>
