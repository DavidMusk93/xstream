<template>
  <Teleport to="body">
    <Transition name="sheet" :duration="{ enter: 450, leave: 220 }">
      <div
        v-if="open"
        class="sheet-root fixed inset-0 z-[90] flex items-end sm:items-center justify-center sm:p-6"
        @pointerdown.self="open = false"
      >
        <div class="sheet-scrim absolute inset-0 bg-black/25 pointer-events-none" />
        <div
          role="dialog"
          aria-modal="true"
          :aria-label="title"
          class="sheet-panel relative w-full sm:max-w-[520px] max-h-[88dvh] overflow-y-auto bg-white rounded-t-[28px] sm:rounded-[28px] shadow-float pb-[env(safe-area-inset-bottom)]"
        >
          <div class="sm:hidden flex justify-center pt-2.5">
            <span class="w-9 h-1 rounded-full bg-black/[0.12]" />
          </div>
          <div class="flex items-start justify-between gap-4 px-6 pt-4 sm:pt-6">
            <div class="min-w-0">
              <h2 class="text-[22px] font-bold text-foreground leading-tight">{{ title }}</h2>
              <p v-if="subtitle" class="mt-1 text-[14px] text-foreground-muted">{{ subtitle }}</p>
            </div>
            <button class="btn-icon -mr-2 -mt-1 bg-black/[0.04] text-foreground-muted" aria-label="Close" @click="open = false">
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round">
                <line x1="18" y1="6" x2="6" y2="18" /><line x1="6" y1="6" x2="18" y2="18" />
              </svg>
            </button>
          </div>
          <div class="px-6 pt-5 pb-6">
            <slot />
          </div>
        </div>
      </div>
    </Transition>
  </Teleport>
</template>

<script setup lang="ts">
const open = defineModel<boolean>('open', { default: false })
defineProps<{ title: string; subtitle?: string }>()

function onKeydown(e: KeyboardEvent) {
  if (e.key === 'Escape') open.value = false
}

watch(open, (isOpen) => {
  document.documentElement.style.overflow = isOpen ? 'hidden' : ''
  if (isOpen) document.addEventListener('keydown', onKeydown)
  else document.removeEventListener('keydown', onKeydown)
})

onUnmounted(() => {
  document.documentElement.style.overflow = ''
  document.removeEventListener('keydown', onKeydown)
})
</script>

<style scoped>
.sheet-enter-active .sheet-scrim {
  transition: opacity 0.3s ease;
}
.sheet-leave-active .sheet-scrim {
  transition: opacity 0.2s ease;
}
.sheet-enter-active .sheet-panel {
  transition: transform 0.45s var(--ease-spring), opacity 0.3s var(--ease-spring);
}
.sheet-leave-active .sheet-panel {
  transition: transform 0.22s ease-in, opacity 0.22s ease-in;
}
.sheet-enter-from .sheet-scrim,
.sheet-leave-to .sheet-scrim {
  opacity: 0;
}
.sheet-enter-from .sheet-panel,
.sheet-leave-to .sheet-panel {
  transform: translateY(100%);
}
@media (min-width: 640px) {
  .sheet-enter-from .sheet-panel,
  .sheet-leave-to .sheet-panel {
    transform: scale(0.95);
    opacity: 0;
  }
}
</style>
