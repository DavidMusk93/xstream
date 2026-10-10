<template>
  <div aria-hidden="true">
    <div class="mb-4 sm:mb-5 px-1 space-y-3">
      <Skeleton class="h-3 w-28 rounded" />
      <Skeleton class="h-9 w-52 rounded-lg" />
    </div>
    <div class="grid gap-6 sm:gap-8 lg:grid-cols-[minmax(0,1.65fr)_minmax(0,1fr)] lg:gap-12">
      <Skeleton class="w-full max-w-[760px] aspect-[3/2] !rounded-[22px]" />
      <div class="flex flex-col gap-3 lg:justify-end">
        <Skeleton class="h-3 w-full rounded" />
        <div class="space-y-3 mt-5 lg:mt-auto">
          <Skeleton class="h-4 w-24 rounded" />
          <Skeleton class="h-12 w-56 rounded-lg" />
          <Skeleton class="h-4 w-full rounded" />
          <Skeleton class="h-4 w-4/6 rounded" />
          <div class="flex gap-3 pt-5">
            <Skeleton v-for="i in 3" :key="i" class="h-12 w-12 !rounded-full" />
          </div>
        </div>
      </div>
    </div>
    <div class="mt-8 sm:mt-10 flex gap-4 sm:gap-5 overflow-hidden">
      <div v-for="i in 7" :key="i" class="shrink-0 w-[148px] sm:w-[188px] lg:w-[212px]">
        <Skeleton class="w-full aspect-[3/2] !rounded-[14px]" />
        <Skeleton class="mt-2.5 h-3 w-20 rounded" />
      </div>
    </div>
  </div>
</template>
