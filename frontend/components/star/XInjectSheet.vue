<template>
  <Sheet v-model:open="open" title="Inject from X" subtitle="Paste from x.com, or let an agent POST JSON for you.">
    <div class="flex gap-1 p-1 rounded-full bg-black/[0.04] mb-3" role="tablist" aria-label="Inject target">
      <button
        type="button"
        role="tab"
        class="flex-1 h-9 rounded-full text-[13px] font-semibold transition-colors"
        :class="mode === 'stars' ? 'bg-white text-foreground shadow-sm' : 'text-foreground-muted hover:text-foreground'"
        :aria-selected="mode === 'stars'"
        @click="mode = 'stars'"
      >
        Library stars
      </button>
      <button
        type="button"
        role="tab"
        class="flex-1 h-9 rounded-full text-[13px] font-semibold transition-colors"
        :class="mode === 'creators' ? 'bg-white text-foreground shadow-sm' : 'text-foreground-muted hover:text-foreground'"
        :aria-selected="mode === 'creators'"
        @click="mode = 'creators'"
      >
        Body creators
      </button>
    </div>

    <form class="space-y-3" aria-label="Inject X posts" @submit.prevent="submit()">
      <label v-if="mode === 'stars'" class="block">
        <span class="sr-only">Star</span>
        <select v-model="target" name="star" class="field pr-10 appearance-none bg-[length:12px] bg-no-repeat bg-[right_1rem_center] select-chevron" aria-label="Star">
          <option value="">Auto — batch JSON names each star</option>
          <option v-for="s in sortedStars" :key="s.code" :value="s.code">
            {{ s.name }}{{ s.x?.handle ? ` · @${s.x.handle}` : s.x?.checked_at ? ' · not on X' : '' }}
          </option>
        </select>
      </label>

      <p class="px-1 text-[13px] text-foreground-muted tabular-nums min-h-[1.25rem]">
        <template v-if="mode === 'creators'">
          Creators you follow on X (not library stars) · newest <strong class="text-foreground font-medium">10</strong> posts each
        </template>
        <template v-else-if="selected">
          <template v-if="selected.x?.handle">
            <span class="text-foreground font-medium">@{{ selected.x.handle }}</span>
            · {{ selected.x.posts.length }} post{{ selected.x.posts.length === 1 ? '' : 's' }}
            · checked {{ ago(selected.x.checked_at) }}
          </template>
          <template v-else-if="selected.x?.checked_at">No X account · checked {{ ago(selected.x.checked_at) }}</template>
          <template v-else>Never checked</template>
        </template>
        <template v-else>{{ pendingStars.length }} of {{ stars.length }} stars need a check</template>
      </p>

      <textarea
        ref="inputRef"
        v-model="content"
        name="content"
        aria-label="X content"
        rows="8"
        spellcheck="false"
        autocomplete="off"
        :placeholder="mode === 'creators' ? PLACEHOLDER_CREATORS : PLACEHOLDER_STARS"
        class="field !h-auto min-h-[180px] max-h-[40dvh] py-3 font-mono text-[13px] leading-[1.5] resize-y"
        @keydown.meta.enter.prevent="submit()"
        @keydown.ctrl.enter.prevent="submit()"
      />

      <div class="flex items-center gap-2.5">
        <button
          v-if="mode === 'stars'"
          type="button"
          class="btn btn-secondary h-12 flex-1"
          :disabled="busy || !target"
          title="Mark this star as having no X account"
          @click="submit('none')"
        >
          Not on X
        </button>
        <button type="submit" class="btn btn-primary h-12 flex-[2]" :disabled="busy || !content.trim()">
          <span v-if="busy" class="spinner w-4 h-4" />
          {{ busy ? 'Injecting…' : 'Inject' }}
        </button>
      </div>
    </form>

    <Transition name="fade">
      <p v-if="error" class="mt-3 text-[14px] text-danger" role="alert">{{ error }}</p>
      <p v-else-if="success" class="mt-3 text-[14px] text-foreground-muted" role="status">
        <span class="text-success font-semibold">✓</span> {{ success }}
      </p>
    </Transition>

    <div class="mt-6 rounded-2xl bg-black/[0.03] p-4">
      <div class="flex items-center justify-between gap-3">
        <div class="min-w-0">
          <p class="text-[14px] font-semibold text-foreground">For your agent</p>
          <p class="mt-0.5 text-[13px] text-foreground-muted">
            One brief with queue + API steps · <span class="tabular-nums">{{ agentSummary }}</span>
          </p>
        </div>
        <button type="button" class="btn btn-sm btn-dark shrink-0" :disabled="briefLoading" @click="copyAgentBrief">
          {{ briefCopied ? 'Copied' : briefLoading ? '…' : 'Copy brief' }}
        </button>
      </div>
      <details class="mt-3 group">
        <summary class="text-[13px] text-foreground-muted cursor-pointer select-none hover:text-foreground transition-colors">
          Agent self-bootstrap (no repo docs)
        </summary>
        <p class="mt-2 text-[13px] text-foreground-muted leading-snug">
          After login, agents call
          <code class="font-mono text-[12px]">GET /api/social/x/agent-brief</code>
          (also linked from <code class="font-mono text-[12px]">GET /api/health</code>).
          Same text as Copy brief.
        </p>
        <ul class="mt-2 space-y-1.5 text-[13px] text-foreground-muted leading-snug">
          <li><span class="text-foreground font-medium">Stars</span> → <code class="font-mono">POST /api/social/x</code> · keep 5</li>
          <li><span class="text-foreground font-medium">Creators</span> → <code class="font-mono">POST /api/social/x/creators</code> · keep 10</li>
          <li>HTML, text (<code class="font-mono">@handle</code> + <code class="font-mono">---</code>), or JSON batch — auto-detected.</li>
        </ul>
      </details>
    </div>
  </Sheet>
</template>

<script setup lang="ts">
import type { Star } from '~/types/api'

const open = defineModel<boolean>('open', { default: false })
const target = defineModel<string>('target', { default: '' })
const props = defineProps<{ stars: Star[] }>()
const emit = defineEmits<{ (e: 'injected', payload: { mode: 'stars' | 'creators' }): void }>()

type Mode = 'stars' | 'creators'
const mode = ref<Mode>('stars')

const PLACEHOLDER_STARS = `@handle
---
https://x.com/handle/status/1846…
Post text
en: English line
---
…or paste x.com HTML / JSON`

const PLACEHOLDER_CREATORS = `{"creators":[{"handle":"username","name":"…","posts":[{"url":"https://x.com/username/status/…","text":"…","en":"…"}]}]}
…or paste a creator profile HTML / @handle text blocks`

const STALE_MS = 72 * 3600 * 1000

const { injectX, injectCreators, getXAgentBrief } = useApi()
const { track } = useTrack()
const { add: addLog } = useEventLog()

const inputRef = ref<HTMLTextAreaElement>()
const content = ref('')
const busy = ref(false)
const error = ref('')
const success = ref('')
const briefCopied = ref(false)
const briefLoading = ref(false)
const agentSummary = ref('fetch on copy')

const sortedStars = computed(() => [...props.stars].sort((a, b) => a.name.localeCompare(b.name)))
const selected = computed(() => props.stars.find(s => s.code === target.value) || null)
const pendingStars = computed(() => props.stars.filter((s) => {
  const t = s.x?.checked_at ? Date.parse(s.x.checked_at) : 0
  return !t || Date.now() - t > STALE_MS || !!s.x?.posts.some(p => !p.en)
}))

function ago(iso: string | null | undefined): string {
  const t = iso ? Date.parse(iso) : NaN
  if (Number.isNaN(t)) return 'never'
  const s = (Date.now() - t) / 1000
  if (s < 3600) return `${Math.max(1, Math.floor(s / 60))}m ago`
  if (s < 86400) return `${Math.floor(s / 3600)}h ago`
  return `${Math.floor(s / 86400)}d ago`
}

watch(open, (isOpen) => {
  if (!isOpen) return
  error.value = ''
  success.value = ''
  nextTick(() => inputRef.value?.focus())
})

watch(target, () => {
  error.value = ''
  success.value = ''
})

watch(mode, () => {
  error.value = ''
  success.value = ''
})

async function submit(raw?: string) {
  const payload = raw ?? content.value.trim()
  if (!payload || busy.value) return
  busy.value = true
  error.value = ''
  success.value = ''
  try {
    if (mode.value === 'creators') {
      let body: string | Record<string, unknown> = payload
      if (payload.startsWith('{') || payload.startsWith('[')) {
        try {
          body = JSON.parse(payload) as Record<string, unknown>
        } catch {
          /* send as text/HTML */
        }
      }
      const res = await injectCreators(body)
      const ok = res.results.filter(r => r.ok)
      const failed = res.results.filter(r => !r.ok)
      if (ok.length === 1 && !failed.length) {
        const r = ok[0]
        success.value = `@${r.handle} · ${r.posts} post${r.posts === 1 ? '' : 's'} shown`
      } else {
        success.value = `Updated ${ok.length} creator${ok.length === 1 ? '' : 's'}`
          + (failed.length ? ` · skipped ${failed.map(f => `@${f.handle ?? '?'} (${f.error})`).join(', ')}` : '')
      }
      if (!raw) content.value = ''
      track('x_inject', { meta: { kind: 'creators', updated: ok.length, failed: failed.length } })
      addLog({ kind: 'action', title: 'Injected creator X posts', detail: success.value, state: 'success' })
      emit('injected', { mode: 'creators' })
    } else {
      const res = await injectX(target.value || null, payload)
      const ok = res.results.filter(r => r.ok)
      const failed = res.results.filter(r => !r.ok)
      if (ok.length === 1 && !failed.length) {
        const r = ok[0]
        success.value = r.handle
          ? `${r.name} · @${r.handle} · ${r.posts} post${r.posts === 1 ? '' : 's'} shown`
          : `${r.name} marked as not on X`
      } else {
        success.value = `Updated ${ok.length} star${ok.length === 1 ? '' : 's'}`
          + (failed.length ? ` · skipped ${failed.map(f => `${f.star ?? '?'} (${f.error})`).join(', ')}` : '')
      }
      if (!raw) content.value = ''
      track('x_inject', { star_code: target.value || undefined, meta: { updated: ok.length, failed: failed.length, none: raw === 'none' } })
      addLog({ kind: 'action', title: 'Injected X posts', detail: success.value, state: 'success' })
      useStars().refreshLibrary().catch(() => {})
      emit('injected', { mode: 'stars' })
    }
  } catch (e: any) {
    const detail = e?.data?.detail || e?.message || 'Inject failed'
    error.value = detail === 'no target star'
      ? 'Pick a star, or paste batch JSON with a "star" per entry.'
      : detail
  } finally {
    busy.value = false
  }
}

async function copyAgentBrief() {
  briefLoading.value = true
  try {
    const data = await getXAgentBrief(72)
    const q = data.work_queue
    agentSummary.value = `${q.stars_needing_check} stars · ${q.creators_stale.length} creators stale`
    await navigator.clipboard.writeText(data.prompt_markdown)
    briefCopied.value = true
    setTimeout(() => { briefCopied.value = false }, 1500)
  } catch (e: any) {
    error.value = e?.message || 'Could not load agent brief'
  } finally {
    briefLoading.value = false
  }
}
</script>

<style scoped>
.select-chevron {
  background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' stroke='%2386868B' stroke-width='2.5' stroke-linecap='round' stroke-linejoin='round'%3E%3Cpolyline points='6 9 12 15 18 9'/%3E%3C/svg%3E");
}
</style>
