<template>
  <header class="chrome fixed inset-x-0 top-0 z-40 pt-[env(safe-area-inset-top)]">
    <div class="max-w-7xl mx-auto px-3 sm:px-6 h-14 flex items-center justify-between gap-2">
      <div class="flex items-center gap-2 min-w-0">
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
      <div class="flex items-center gap-0.5 sm:gap-1">
        <slot name="actions" />
      </div>
    </div>
    <slot />
  </header>
</template>

<script setup lang="ts">
defineProps<{ offline?: boolean }>()
</script>
