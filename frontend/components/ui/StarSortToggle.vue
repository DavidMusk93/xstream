<template>
  <span class="inline-flex items-center gap-1 shrink-0" role="radiogroup" aria-label="Sort stars">
    <span class="text-foreground-muted">Sort</span>
    <button
      type="button"
      role="radio"
      class="h-7 px-2.5 rounded-full text-[12px] font-medium transition-[background-color,color,transform] duration-300 ease-spring active:scale-[0.96] active:duration-100"
      :class="model === 'release'
        ? 'bg-foreground text-white'
        : 'text-foreground-muted hover:text-foreground hover:bg-black/[0.05]'"
      :aria-checked="model === 'release' ? 'true' : 'false'"
      title="按作品发布日期 (Newest release date first)"
      @click="model = 'release'"
    >
      Release
    </button>
    <button
      type="button"
      role="radio"
      class="h-7 px-2.5 rounded-full text-[12px] font-medium transition-[background-color,color,transform] duration-300 ease-spring active:scale-[0.96] active:duration-100"
      :class="model === 'discovered'
        ? 'bg-foreground text-white'
        : 'text-foreground-muted hover:text-foreground hover:bg-black/[0.05]'"
      :aria-checked="model === 'discovered' ? 'true' : 'false'"
      title="按作品发现/入库日期 (Recently discovered on xstream first)"
      @click="model = 'discovered'"
    >
      Discovered
    </button>
    <button
      type="button"
      role="radio"
      class="h-7 px-2.5 rounded-full text-[12px] font-medium transition-[background-color,color,transform] duration-300 ease-spring active:scale-[0.96] active:duration-100"
      :class="model === 'added'
        ? 'bg-foreground text-white'
        : 'text-foreground-muted hover:text-foreground hover:bg-black/[0.05]'"
      :aria-checked="model === 'added' ? 'true' : 'false'"
      title="按关注时间 (Recently followed star first)"
      @click="model = 'added'"
    >
      Followed
    </button>
  </span>
</template>

<script setup lang="ts">
import type { StarSort } from '~/utils/starSort'

const model = defineModel<StarSort>({ required: true })
</script>
