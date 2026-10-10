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

const props = defineProps<{
  stars: Star[]
}>()

const activeStar = ref('')
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
  activeStar.value = code
  const el = document.getElementById(`star-${code.toLowerCase()}`)
  if (el) {
    el.scrollIntoView({ behavior: 'smooth', block: 'start' })
  }
}

let observer: IntersectionObserver | null = null
// Codes whose section element is currently observed. Stars load client-side
// after mount and the roster churns (adds/deletes), so observations must be
// diffed on every refresh: observe new sections, unobserve removed ones
// (a deleted star's detached element would otherwise stay observed).
const observed = new Set<string>()

function syncObserved() {
  if (!observer) return
  const current = new Set(props.stars.map(s => s.code))
  for (const code of observed) {
    if (!current.has(code)) {
      const el = document.getElementById(`star-${code.toLowerCase()}`)
      if (el) observer.unobserve(el)
      observed.delete(code)
    }
  }
  for (const star of props.stars) {
    if (observed.has(star.code)) continue
    const el = document.getElementById(`star-${star.code.toLowerCase()}`)
    if (el) {
      observer.observe(el)
      observed.add(star.code)
    }
  }
}

onMounted(() => {
  observer = new IntersectionObserver(
    (entries) => {
      entries.forEach((entry) => {
        if (entry.isIntersecting) {
          const idCode = entry.target.id.replace('star-', '').toUpperCase()
          activeStar.value = idCode
        }
      })
    },
    { rootMargin: '-30% 0px -60% 0px' }
  )
  syncObserved()
})

onUnmounted(() => {
  if (observer) observer.disconnect()
  observed.clear()
})

watch(() => props.stars, (stars) => {
  if (!activeStar.value && stars.length) activeStar.value = stars[0].code
  nextTick(syncObserved)
}, { immediate: true })
</script>
