<template>
  <span class="inline-flex items-center gap-1 shrink-0" role="radiogroup" aria-label="Sort stars">
    <span class="text-foreground-muted">Sort</span>
    <button
      type="button"
      role="radio"
      class="h-7 px-2.5 rounded-full text-[12px] font-medium transition-[background-color,color,transform] duration-300 ease-spring active:scale-[0.96] active:duration-100"
      :class="model === 'works'
        ? 'bg-foreground text-white'
        : 'text-foreground-muted hover:text-foreground hover:bg-black/[0.05]'"
      :aria-checked="model === 'works' ? 'true' : 'false'"
      title="Newest work first (release date, then discovery log)"
      @click="model = 'works'"
    >
      Latest
    </button>
    <button
      type="button"
      role="radio"
      class="h-7 px-2.5 rounded-full text-[12px] font-medium transition-[background-color,color,transform] duration-300 ease-spring active:scale-[0.96] active:duration-100"
      :class="model === 'added'
        ? 'bg-foreground text-white'
        : 'text-foreground-muted hover:text-foreground hover:bg-black/[0.05]'"
      :aria-checked="model === 'added' ? 'true' : 'false'"
      title="Recently followed first"
      @click="model = 'added'"
    >
      Added
    </button>
  </span>
</template>

<script setup lang="ts">
import type { StarSort } from '~/utils/starSort'

const model = defineModel<StarSort>({ required: true })
</script>
