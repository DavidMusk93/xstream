<template>
  <div
    class="scroll-rail fixed z-30 left-1/2 -translate-x-1/2 sm:left-auto sm:translate-x-0 sm:right-6 flex items-center gap-0.5 transition-[opacity,transform] duration-300 ease-spring"
    :class="visible ? 'opacity-100 translate-y-0' : 'opacity-0 translate-y-2 pointer-events-none'"
    style="bottom: max(1.25rem, env(safe-area-inset-bottom))"
    role="group"
    aria-label="Scroll"
    :aria-hidden="!visible"
  >
    <button
      type="button"
      class="btn-icon"
      :class="{ '!opacity-30': atTop }"
      :disabled="atTop"
      title="Back to top"
      aria-label="Back to top"
      @click="emit('scroll', 'top')"
    >
      <svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round">
        <polyline points="18 15 12 9 6 15" />
      </svg>
    </button>
    <button
      type="button"
      class="btn-icon"
      :class="{ '!opacity-30': atBottom }"
      :disabled="atBottom"
      title="Jump to bottom"
      aria-label="Jump to bottom"
      @click="emit('scroll', 'bottom')"
    >
      <svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round">
        <polyline points="6 9 12 15 18 9" />
      </svg>
    </button>
  </div>
</template>

<script setup lang="ts">
defineProps<{
  visible: boolean
  atTop: boolean
  atBottom: boolean
}>()

const emit = defineEmits<{ (e: 'scroll', to: 'top' | 'bottom'): void }>()
</script>
