<template>
  <Transition
    enter-active-class="transition duration-500 ease-spring"
    enter-from-class="-translate-y-3 scale-[0.96] opacity-0"
    enter-to-class="translate-y-0 scale-100 opacity-100"
    leave-active-class="transition duration-200 ease-in"
    leave-from-class="translate-y-0 scale-100 opacity-100"
    leave-to-class="-translate-y-2 scale-[0.98] opacity-0"
  >
    <div
      v-if="visible"
      role="status"
      class="popover fixed top-[calc(env(safe-area-inset-top)+12px)] inset-x-0 mx-auto z-[60] flex items-start gap-3 px-4 py-3.5 max-w-[420px] w-[calc(100vw-24px)]"
      :class="state !== 'running' ? 'cursor-pointer' : ''"
      @click="state !== 'running' && $emit('dismiss')"
    >
      <!-- Status icon -->
      <span
        class="w-7 h-7 rounded-full flex items-center justify-center shrink-0"
        :class="iconBgClass"
      >
        <span v-if="state === 'running'" class="spinner w-3.5 h-3.5" />
        <svg v-else-if="state === 'success'" width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round" stroke-linejoin="round">
          <polyline points="20 6 9 17 4 12" />
        </svg>
        <svg v-else width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
          <circle cx="12" cy="12" r="10" />
          <line x1="12" y1="8" x2="12" y2="12" />
          <line x1="12" y1="16" x2="12.01" y2="16" />
        </svg>
      </span>

      <!-- Text + progress -->
      <div class="flex-1 min-w-0">
        <div class="flex items-baseline justify-between gap-2 pt-[3px]">
          <p class="text-[14px] font-semibold text-foreground leading-snug">{{ title }}</p>
          <span v-if="progressText" class="text-[12px] font-medium text-foreground-muted tabular-nums shrink-0">
            {{ progressText }}
          </span>
        </div>
        <p v-if="detail" class="text-[13px] text-foreground-muted mt-0.5 leading-snug truncate">{{ detail }}</p>

        <!-- Progress bar -->
        <div v-if="state === 'running'" class="mt-2.5 h-1 rounded-full bg-black/[0.06] overflow-hidden">
          <div
            class="h-full rounded-full bg-accent transition-[width] duration-700 ease-spring"
            :style="{ width: `${Math.max(4, Math.round(fraction * 100))}%` }"
          />
        </div>
      </div>

      <button
        v-if="state !== 'running'"
        class="w-6 h-6 -mr-1 rounded-full flex items-center justify-center text-foreground-muted/60 hover:text-foreground hover:bg-black/[0.05] transition-colors shrink-0"
        aria-label="Dismiss"
        @click.stop="$emit('dismiss')"
      >
        <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
          <line x1="18" y1="6" x2="6" y2="18" />
          <line x1="6" y1="6" x2="18" y2="18" />
        </svg>
      </button>
    </div>
  </Transition>
</template>

<script setup lang="ts">
const props = defineProps<{
  visible: boolean
  state: 'running' | 'success' | 'error'
  title: string
  detail?: string
  progressText?: string
  fraction: number
}>()

defineEmits<{
  (e: 'dismiss'): void
}>()

const iconBgClass = computed(() => {
  switch (props.state) {
    case 'running': return 'bg-accent/10 text-accent'
    case 'success': return 'bg-success/15 text-success'
    case 'error': return 'bg-danger/15 text-danger'
  }
})
</script>
