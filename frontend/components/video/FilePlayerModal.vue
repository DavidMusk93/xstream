<template>
  <Teleport to="body">
    <Transition name="player" :duration="{ enter: 450, leave: 200 }">
      <div
        v-if="isOpen"
        class="player-root fixed inset-0 z-[100] flex items-center justify-center bg-black/90 backdrop-blur-xl"
        @click.self="close"
      >
        <div class="player-stage relative w-full h-full sm:w-[92vw] sm:max-w-6xl sm:h-auto sm:aspect-video bg-black sm:rounded-[22px] overflow-hidden shadow-2xl">
          <!-- Top bar -->
          <div class="absolute top-0 inset-x-0 z-30 flex items-center justify-between gap-4 pl-5 pr-3 pt-[max(12px,env(safe-area-inset-top))] pb-10 sm:pt-4 bg-gradient-to-b from-black/60 to-transparent">
            <p class="text-[15px] font-semibold text-white/95 truncate">{{ fileName }}</p>

            <button
              class="w-10 h-10 shrink-0 rounded-full bg-white/[0.12] backdrop-blur-md text-white flex items-center justify-center transition hover:bg-white/20 active:scale-[0.92]"
              aria-label="Close player"
              @click="close"
            >
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
                <line x1="18" y1="6" x2="6" y2="18"/>
                <line x1="6" y1="6" x2="18" y2="18"/>
              </svg>
            </button>
          </div>

          <video
            v-if="src"
            :key="src"
            :src="src"
            controls
            autoplay
            playsinline
            webkit-playsinline
            preload="auto"
            class="w-full h-full object-contain"
          />
        </div>
      </div>
    </Transition>
  </Teleport>
</template>

<script setup lang="ts">
const isOpen = defineModel<boolean>('open', { default: false })
const props = defineProps<{ path?: string }>()

const ostore = useOstore()
const src = ref('')

const fileName = computed(() => props.path?.split('/').pop() ?? '')

watch([() => props.path, isOpen], async ([path, open]) => {
  if (!open || !path) return
  try {
    src.value = await ostore.fileUrl(path)
  } catch {
    src.value = ''
  }
})

watch(isOpen, (open) => {
  // Clearing :src unmounts the <video>, which pauses playback and drops the
  // connection — no explicit pause needed.
  if (!open) src.value = ''
})

function close() {
  isOpen.value = false
}
</script>

<style scoped>
.player-enter-active {
  transition: opacity 0.3s ease;
}
.player-enter-active .player-stage {
  transition: transform 0.45s var(--ease-spring), opacity 0.3s var(--ease-spring);
}
.player-leave-active,
.player-leave-active .player-stage {
  transition: opacity 0.2s ease, transform 0.2s ease;
}
.player-enter-from,
.player-leave-to {
  opacity: 0;
}
.player-enter-from .player-stage,
.player-leave-to .player-stage {
  transform: scale(0.96);
}
</style>
