<template>
  <nav class="max-w-7xl mx-auto sm:px-3">
    <div ref="railRef" class="relative flex items-center gap-1 px-3 pb-2.5 overflow-x-auto scrollbar-hide sm:fade-edges-x">
      <a
        v-for="star in stars"
        :key="star.code"
        :href="`#star-${star.code.toLowerCase()}`"
        :data-nav="star.code"
        class="shrink-0 h-8 px-3.5 inline-flex items-center rounded-full text-[14px] font-medium transition-[background-color,color,transform] duration-300 ease-spring active:scale-[0.96] active:duration-100"
        :class="activeStar === star.code
          ? 'bg-foreground text-white'
          : 'text-foreground-muted hover:text-foreground hover:bg-black/[0.05]'"
        @click.prevent="scrollToStar(star.code)"
      >
        {{ star.name }}
      </a>
    </div>
  </nav>
</template>

<script setup lang="ts">
import type { Star } from '~/types/api'

// The active star is tracked by the page (it observes each section as it
// mounts); the nav only renders it and requests jumps.
const props = defineProps<{
  stars: Star[]
  active: string
}>()

const emit = defineEmits<{ (e: 'select', code: string): void }>()

const activeStar = computed(() => props.active || props.stars[0]?.code || '')
const railRef = ref<HTMLElement | null>(null)

// Keep the active pill centered in the rail. Scrolls the rail itself —
// scrollIntoView would also nudge the page, fighting the section scroll.
watch(activeStar, (code) => {
  const rail = railRef.value
  const pill = rail?.querySelector<HTMLElement>(`[data-nav="${code}"]`)
  if (!rail || !pill) return
  const target = pill.offsetLeft - (rail.clientWidth - pill.offsetWidth) / 2
  rail.scrollTo({ left: Math.max(0, target), behavior: 'smooth' })
})

function scrollToStar(code: string) {
  emit('select', code)
  const el = document.getElementById(`star-${code.toLowerCase()}`)
  if (el) {
    el.scrollIntoView({ behavior: 'smooth', block: 'start' })
  }
}
</script>
