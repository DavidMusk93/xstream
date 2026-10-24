<template>
  <header class="chrome fixed inset-x-0 top-0 z-40 pt-[env(safe-area-inset-top)]" :class="{ 'chrome-flat': atTop && !railOverflows }">
    <div class="max-w-7xl mx-auto px-3 sm:px-6 h-14 flex items-center justify-between gap-1 sm:gap-2">
      <div class="flex items-center gap-2 shrink-0">
        <slot name="leading">
          <NuxtLink to="/" class="flex items-center gap-2.5 pl-1 pr-2 h-10 rounded-full pressable" aria-label="xstream home">
            <img src="/logo.png" alt="" class="w-7 h-7 rounded-[8px]" />
            <span class="text-[19px] font-semibold text-foreground tracking-tight">xstream</span>
          </NuxtLink>
        </slot>
        <span
          v-if="offline"
          class="chip bg-danger/10 text-danger"
          title="Backend unreachable"
        >
          <span class="w-1.5 h-1.5 rounded-full bg-danger" />Offline
        </span>
      </div>
      <!-- Phones: the actions are a horizontal rail that scrolls under the
           logo instead of overlapping it; edges fade while more is hidden.
           Fades are overlays, not a mask: a mask would also clip the fixed
           popovers rendered inside the rail. From sm: up the rail must stay
           overflow-visible — popovers anchor under their trigger there. -->
      <div class="relative min-w-0">
        <div
          ref="railRef"
          class="overflow-x-auto scrollbar-hide sm:overflow-visible"
          @scroll.passive="updateFades"
        >
          <div class="flex items-center gap-0.5 sm:gap-1 w-max ml-auto">
            <slot name="actions" />
          </div>
        </div>
        <span
          class="rail-fade left-0 bg-gradient-to-r"
          :class="{ on: fadeL }"
          aria-hidden="true"
        />
        <span
          class="rail-fade right-0 bg-gradient-to-l"
          :class="{ on: fadeR }"
          aria-hidden="true"
        />
      </div>
    </div>
    <slot />
  </header>
</template>

<script setup lang="ts">
defineProps<{ offline?: boolean }>()

const atTop = ref(true)
function onScroll() {
  atTop.value = window.scrollY < 8
}

const railRef = ref<HTMLElement | null>(null)
const fadeL = ref(false)
const fadeR = ref(false)
const railOverflows = ref(false)
function updateFades() {
  const el = railRef.value
  if (!el) return
  const max = el.scrollWidth - el.clientWidth
  railOverflows.value = max > 2
  fadeL.value = el.scrollLeft > 2
  fadeR.value = max - el.scrollLeft > 2
}

let ro: ResizeObserver | null = null
onMounted(() => {
  onScroll()
  window.addEventListener('scroll', onScroll, { passive: true })
  updateFades()
  if (railRef.value) {
    ro = new ResizeObserver(updateFades)
    ro.observe(railRef.value)
    if (railRef.value.firstElementChild) ro.observe(railRef.value.firstElementChild)
  }
})
onUnmounted(() => {
  window.removeEventListener('scroll', onScroll)
  ro?.disconnect()
})
</script>

<style scoped>
.rail-fade {
  @apply absolute inset-y-0 w-7 from-white to-transparent pointer-events-none opacity-0 sm:hidden;
  transition: opacity 0.2s var(--ease-out);
}
.rail-fade.on {
  opacity: 1;
}
</style>
