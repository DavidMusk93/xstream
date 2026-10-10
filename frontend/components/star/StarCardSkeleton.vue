<template>
  <div aria-hidden="true">
    <div class="mb-4 sm:mb-5 px-1 space-y-3">
      <Skeleton class="h-3 w-28 rounded" />
      <Skeleton class="h-9 w-52 rounded-lg" />
    </div>
    <div class="surface overflow-hidden">
      <div class="flex flex-col sm:flex-row gap-5 sm:gap-8 p-4 sm:p-6">
        <Skeleton class="w-full sm:w-[300px] md:w-[360px] lg:w-[440px] shrink-0 aspect-[3/2] !rounded-[18px]" />
        <div class="flex-1 space-y-3 sm:py-6">
          <Skeleton class="h-4 w-28 rounded" />
          <Skeleton class="h-10 w-48 rounded-lg" />
          <Skeleton class="h-4 w-full rounded" />
          <Skeleton class="h-4 w-4/6 rounded" />
          <div class="flex gap-3 pt-4">
            <Skeleton v-for="i in 3" :key="i" class="h-12 w-12 !rounded-full" />
          </div>
        </div>
      </div>
      <div class="flex gap-3 sm:gap-4 overflow-hidden px-4 sm:px-6 py-4 sm:py-5 border-t border-black/[0.05]">
        <Skeleton v-for="i in 7" :key="i" class="shrink-0 w-[112px] sm:w-[144px] md:w-[168px] aspect-[3/2] !rounded-xl" />
      </div>
    </div>
  </div>
</template>
