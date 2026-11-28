<template>
  <section :id="id" class="group/star relative isolate" :style="auraSectionStyle">
    <!-- Section header: name sits on the page, the shelf below is one surface -->
    <div v-reveal class="flex items-end justify-between gap-4 mb-4 sm:mb-5 px-1">
      <div class="min-w-0">
        <div class="eyebrow flex-wrap">
          <span class="transition-colors duration-500" :style="{ color: `rgb(${auraRgb})` }">{{ String((index ?? 0) + 1).padStart(2, '0') }}</span>
          <span class="tabular-nums">{{ star.titles?.length ?? 0 }} titles</span>
          <span v-if="starAura.careerYears" class="tabular-nums text-foreground-muted/80">{{ starAura.careerYears }}y</span>
          <div ref="auraPopoverRoot" class="relative inline-flex items-center">
            <button
              type="button"
              data-aura-trigger
              class="inline-flex items-center gap-1.5 px-1.5 py-0.5 -my-0.5 rounded-full text-[11px] font-medium text-foreground-muted hover:text-foreground hover:bg-black/[0.04] transition-all duration-200 active:scale-[0.95]"
              :aria-expanded="auraOpen"
              aria-label="Palette & profile"
              @click="toggleAuraPanel"
            >
              <span
                class="w-2.5 h-2.5 rounded-full shrink-0 transition-all duration-500"
                :style="{
                  backgroundColor: `rgb(${auraRgb})`,
                  boxShadow: `0 0 8px rgba(${auraRgb}, 0.55)`,
                }"
              />
              <span v-if="auraTraitBrief" class="hidden sm:inline text-foreground-muted/75">{{ auraTraitBrief }}</span>
            </button>

            <Transition name="pop">
              <div
                v-if="auraOpen"
                class="popover absolute left-0 top-full mt-2 w-[300px] sm:w-[320px] p-4 z-40 origin-top-left font-sans tracking-normal text-left"
              >
                <div
                  class="h-2 w-full rounded-full mb-3 transition-all duration-500"
                  :style="{
                    background: `linear-gradient(90deg, rgb(${auraRgb}), rgb(${auraDeepRgb}))`,
                    boxShadow: `0 4px 16px -4px rgba(${auraRgb}, 0.55)`,
                  }"
                />
                <div class="flex items-center justify-between gap-2">
                  <p class="text-[13px] font-semibold text-foreground">{{ star.name }}</p>
                  <button
                    type="button"
                    class="text-[12px] font-medium px-2.5 py-1 rounded-full bg-black/[0.05] text-foreground hover:bg-black/[0.09] transition"
                    @click="editingProfile = !editingProfile"
                  >
                    {{ editingProfile ? 'Done' : 'Edit' }}
                  </button>
                </div>

                <div v-if="!editingProfile" class="mt-3 space-y-3 text-[12px]">
                  <!-- 16-palette one-click chromatic style selector -->
                  <div>
                    <div class="flex items-center justify-between mb-1.5">
                      <span class="text-[10px] uppercase tracking-wider text-foreground-muted/70">Palette</span>
                      <button
                        v-if="localProfile.style"
                        type="button"
                        class="text-[11px] text-foreground-muted hover:text-foreground transition-colors"
                        @click="selectPalette(null)"
                      >
                        Reset Auto
                      </button>
                    </div>
                    <div class="grid grid-cols-8 gap-1.5">
                      <button
                        v-for="(p, pi) in STAR_PALETTES"
                        :key="p.id"
                        type="button"
                        class="w-6 h-6 rounded-full transition-transform duration-200 ease-spring hover:scale-115 active:scale-95"
                        :class="starAura.id === p.id ? 'ring-2 ring-offset-2 ring-foreground scale-110' : 'ring-1 ring-black/10'"
                        :style="{ backgroundColor: p.swatch }"
                        :aria-label="`Palette ${pi + 1}`"
                        @click="selectPalette(p.id)"
                      />
                    </div>
                  </div>

                  <div class="grid grid-cols-2 gap-2">
                  <div class="rounded-xl bg-black/[0.03] px-2.5 py-2">
                    <p class="text-[10px] uppercase tracking-wider text-foreground-muted/70">Career</p>
                    <p class="mt-0.5 font-medium text-foreground tabular-nums">
                      {{ starAura.debutYear ? `${starAura.debutYear} · ${starAura.careerYears} yrs` : '—' }}
                    </p>
                  </div>
                  <div class="rounded-xl bg-black/[0.03] px-2.5 py-2">
                    <p class="text-[10px] uppercase tracking-wider text-foreground-muted/70">Age</p>
                    <p class="mt-0.5 font-medium text-foreground tabular-nums">
                      {{ starAura.age ? `${starAura.age} (${localProfile.birth_year})` : 'Not set' }}
                    </p>
                  </div>
                  <div class="rounded-xl bg-black/[0.03] px-2.5 py-2">
                    <p class="text-[10px] uppercase tracking-wider text-foreground-muted/70">Height</p>
                    <p class="mt-0.5 font-medium text-foreground tabular-nums">
                      {{ localProfile.height_cm ? `${localProfile.height_cm} cm` : 'Not set' }}
                    </p>
                  </div>
                  <div class="rounded-xl bg-black/[0.03] px-2.5 py-2">
                    <p class="text-[10px] uppercase tracking-wider text-foreground-muted/70">Silhouette</p>
                    <p class="mt-0.5 font-medium text-foreground tabular-nums truncate">
                      {{ [localProfile.cup ? `${localProfile.cup} cup` : '', localProfile.measurements || ''].filter(Boolean).join(' · ') || 'Not set' }}
                    </p>
                  </div>
                  </div>
                </div>

                <form v-else class="mt-3 space-y-2 text-[12px]" @submit.prevent="saveProfile">
                  <div class="grid grid-cols-2 gap-2">
                    <input v-model.number="profileForm.birth_year" type="number" min="1970" max="2012" placeholder="Birth yr (e.g. 1999)" class="field !h-9 !px-3 !text-[12px] !rounded-xl" />
                    <input v-model.number="profileForm.height_cm" type="number" min="135" max="200" placeholder="Height cm (e.g. 166)" class="field !h-9 !px-3 !text-[12px] !rounded-xl" />
                  </div>
                  <div class="grid grid-cols-2 gap-2">
                    <input v-model="profileForm.cup" type="text" maxlength="2" placeholder="Cup (e.g. E)" class="field !h-9 !px-3 !text-[12px] !rounded-xl uppercase" />
                    <input v-model.number="profileForm.debut_year" type="number" min="1998" max="2030" placeholder="Debut yr" class="field !h-9 !px-3 !text-[12px] !rounded-xl" />
                  </div>
                  <input v-model="profileForm.measurements" type="text" maxlength="48" placeholder="Measurements (e.g. B88 W58 H88)" class="field !h-9 !px-3 !text-[12px] !rounded-xl" />
                  <button type="submit" class="btn btn-primary !h-9 w-full !text-[13px]" :disabled="savingProfile">
                    {{ savingProfile ? 'Saving…' : 'Save & Tune Aura' }}
                  </button>
                </form>
              </div>
            </Transition>
          </div>
          <a
            v-if="star.x?.handle && !star.x.posts?.length"
            :href="`https://x.com/${star.x.handle}`"
            target="_blank"
            rel="noopener noreferrer"
            class="hover:text-foreground transition-colors"
          >@{{ star.x.handle }}</a>
          <span class="h-px w-10 bg-black/10" />
        </div>
        <h2 class="mt-2 text-[28px] sm:text-[36px] font-bold text-foreground leading-[1.1] truncate">
          {{ star.name }}
        </h2>
      </div>
      <div class="flex items-center gap-1 shrink-0">
        <button
          class="btn-icon text-foreground-muted hover:text-foreground sm:opacity-0 sm:group-hover/star:opacity-100 focus-visible:opacity-100"
          :title="`X posts for ${star.name}`"
          :aria-label="`X posts for ${star.name}`"
          @click="emit('social', star.code)"
        >
          <XGlyph class="w-[15px] h-[15px]" />
        </button>
        <button
          class="btn-icon text-foreground-muted hover:text-danger hover:bg-danger/10 sm:opacity-0 sm:group-hover/star:opacity-100 focus-visible:opacity-100"
          title="Unfollow star"
          aria-label="Unfollow star"
          :disabled="deleting"
          @click="onDelete"
        >
          <svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <polyline points="3 6 5 6 21 6" />
            <path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2" />
          </svg>
        </button>
      </div>
    </div>

    <div v-reveal="0.08" class="relative">
      <!-- Ambient chromatic light field driven by her persona aura + active cover tint -->
      <div
        class="star-aura-glow pointer-events-none absolute -inset-x-6 sm:-inset-x-10 -top-6 sm:-top-8 -bottom-4 rounded-[48px] opacity-85 z-0"
        aria-hidden="true"
      />
      <!-- Stage: the cover is the protagonist; info reads like a caption -->
      <div v-if="activeTitle" class="relative z-10 grid gap-6 sm:gap-8 lg:grid-cols-[minmax(0,1.65fr)_minmax(0,1fr)] lg:gap-12">
        <div
          ref="heroStageRef"
          class="hero-stage group/hero relative w-full max-w-[760px] rounded-[22px] overflow-hidden bg-fill shadow-[0_30px_60px_-34px_rgba(0,0,0,0.5)] touch-pan-y select-none outline-none"
          :class="{
            'controls-shown': controlsShown,
            'hero-recoil-left': recoilDir === 'left',
            'hero-recoil-right': recoilDir === 'right',
          }"
          :data-recoil-dir="recoilDir || undefined"
          tabindex="0"
          role="group"
          :aria-label="`${activeTitle.code} cover, swipe or use arrow keys to browse titles`"
          @keydown="onHeroKeydown"
          @pointermove="onStageGlintMove"
        >
          <!-- 波光粼粼 — sunlit water mirror glint + directional caustic ripple on slide -->
          <div class="water-glint" aria-hidden="true" />
          <div
            :key="waterWaveKey"
            class="water-caustic-wave"
            :class="{
              'is-flowing-left': waterWaveKey > 0 && waterWaveDir === 'left',
              'is-flowing-right': waterWaveKey > 0 && waterWaveDir === 'right',
            }"
            aria-hidden="true"
          />
          <div
            ref="heroFrameRef"
            class="hero-frame relative w-full aspect-[3/2] bg-fill overflow-hidden touch-pan-y select-none"
            :class="{
              'hero-dragging-h': dragging,
              'sm:cursor-grab sm:active:cursor-grabbing': total > 1,
            }"
            @pointerdown="onHeroPointerDown"
            @pointermove="(e) => onPointerMove(e, clampDrag)"
            @pointerup="onPointerUp"
            @pointercancel="onPointerCancel"
            @wheel="onWheel"
          >
            <!-- One compositor track: fixed stage box, slides translate — no per-step img swap -->
            <div
              ref="heroTrackRef"
              class="hero-track flex h-full"
              :class="{ 'hero-track-anim': !dragging }"
              :style="heroTrackStyle"
            >
              <div
                v-for="{ title, idx } in windowedHeroSlides"
                :key="title.code"
                class="hero-cell relative shrink-0 h-full overflow-hidden bg-fill"
                :style="heroCellStyle"
                :aria-hidden="idx !== displayIndex"
              >
                <img
                  v-if="heroLqipSrc(title) && !heroCoverReady(title.code) && !heroErrors[title.code]"
                  :src="heroLqipSrc(title)!"
                  alt=""
                  aria-hidden="true"
                  decoding="async"
                  draggable="false"
                  class="hero-lqip absolute inset-0 w-full h-full object-contain pointer-events-none"
                />
                <img
                  v-if="title.cover_url && !heroErrors[title.code]"
                  :src="heroSrc(title)"
                  :srcset="heroSrcset(title)"
                  sizes="(min-width: 1280px) 740px, (min-width: 1024px) 60vw, (min-width: 808px) 760px, calc(100vw - 32px)"
                  :alt="idx === displayIndex ? title.code : ''"
                  :fetchpriority="idx === displayIndex ? 'high' : 'low'"
                  :loading="idx === displayIndex ? 'eager' : 'lazy'"
                  decoding="async"
                  draggable="false"
                  class="hero-hi absolute inset-0 w-full h-full object-contain block [transition-timing-function:var(--ease-out)]"
                  :class="slideHeroImgClass(title, idx)"
                  :ref="(el) => bindHeroImgEl(title, el as HTMLImageElement | null)"
                  @load="(e) => onHeroSlideLoad(title, e)"
                  @error="heroErrors[title.code] = true"
                />
                <div
                  v-else-if="!title.cover_url || heroErrors[title.code]"
                  class="absolute inset-0 flex flex-col items-center justify-center p-6 text-center"
                >
                  <span class="text-[19px] font-semibold text-foreground/50">{{ title.code }}</span>
                  <span class="mt-1.5 text-[14px] text-foreground-muted/70 line-clamp-3">{{ title.title }}</span>
                </div>
              </div>
            </div>
          </div>

          <!-- Stepping lives on the cover itself: revealed by hover / focus
               on desktop, briefly by a swipe on touch -->
          <template v-if="total > 1">
            <button
              type="button"
              data-hero-nav
              data-hero-chrome
              class="hero-nav left-3 sm:left-4 z-10"
              :class="{ 'is-off': displayIndex <= 0 }"
              aria-label="Previous title"
              :disabled="displayIndex <= 0"
              @click="step(-1, { fromChrome: true })"
            >
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"><polyline points="15 18 9 12 15 6" /></svg>
            </button>
            <button
              type="button"
              data-hero-nav
              data-hero-chrome
              class="hero-nav right-3 sm:right-4 z-10"
              :class="{ 'is-off': displayIndex >= total - 1 }"
              aria-label="Next title"
              :disabled="displayIndex >= total - 1"
              @click="step(1, { fromChrome: true })"
            >
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"><polyline points="9 18 15 12 9 6" /></svg>
            </button>
            <span class="hero-count font-mono z-10" data-hero-chrome>{{ displayIndex + 1 }} / {{ total }}</span>
          </template>
        </div>

        <div class="min-w-0 flex flex-col lg:py-1 lg:pb-2">
            <div class="lg:mt-auto">
              <Transition name="editorial-swap" mode="out-in">
                <div :key="activeTitle.code">
                  <div class="flex items-center flex-wrap gap-x-2 gap-y-1 text-[13px] font-medium text-foreground-muted tabular-nums">
                    <span v-if="activeTitle.date">{{ fmtDate(activeTitle.date) }}</span>
                    <span v-if="activeIsHd" class="chip bg-black/[0.06] text-foreground">HD</span>
                    <span v-if="activeTitle.magnet_status === 'dead'" class="chip bg-danger/10 text-danger">Unavailable</span>
                  </div>
                  <h3 class="mt-2 text-[34px] sm:text-[48px] lg:text-[56px] font-bold text-foreground leading-[1] tracking-[-0.03em]">
                    {{ activeTitle.code }}
                  </h3>
                  <p class="mt-4 text-[15px] sm:text-[17px] text-foreground-muted leading-relaxed line-clamp-3 lg:line-clamp-4">
                    {{ activeTitle.title }}
                  </p>
                </div>
              </Transition>

              <!-- Icon-only actions; Copy stays first and accent — it is the
                   real primary action (49 copies vs 1 play in early tracking) -->
              <div class="flex items-center gap-3 mt-6 sm:mt-8">
                <button
                  type="button"
                  class="action text-white hover:-translate-y-1 hover:scale-[1.04]"
                  :class="copied ? 'bg-success shadow-none animate-sensual-pop' : 'action-aura'"
                  :data-tip="copied ? 'Copied' : 'Copy magnet'"
                  :data-tip-show="copied || undefined"
                  aria-label="Copy magnet"
                  :disabled="!activePlayable"
                  @click="copyMagnet"
                >
                  <Transition name="icon-swap" mode="out-in">
                    <MagnetIcon v-if="!copied" key="copy" />
                    <svg v-else key="done" width="19" height="19" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.8" stroke-linecap="round" stroke-linejoin="round">
                      <polyline points="20 6 9 17 4 12" />
                    </svg>
                  </Transition>
                </button>

                <button
                  type="button"
                  class="action bg-foreground text-white hover:bg-black hover:-translate-y-1 hover:scale-[1.04]"
                  data-tip="Play"
                  aria-label="Play"
                  :disabled="!activePlayable"
                  @click="onPlay"
                >
                  <svg width="17" height="17" viewBox="0 0 24 24" fill="currentColor" class="ml-0.5"><path d="M7 4.5v15l12.5-7.5z" /></svg>
                </button>

                <button
                  type="button"
                  class="action hover:-translate-y-1 hover:scale-[1.04]"
                  :class="[
                    activeLiked ? '' : 'bg-black/[0.05] text-foreground hover:bg-black/[0.08]',
                    justLiked ? 'animate-heart-sensual' : ''
                  ]"
                  :style="activeLiked ? { backgroundColor: `rgba(${auraRgb}, 0.14)`, color: `rgb(${auraRgb})` } : undefined"
                  :data-tip="activeLiked ? `Liked ${activeTitle?.code ?? ''}` : `Like ${activeTitle?.code ?? ''}`"
                  :aria-pressed="activeLiked"
                  :aria-label="activeLiked ? `Unlike ${activeTitle?.code ?? ''}` : `Like ${activeTitle?.code ?? ''}`"
                  :disabled="activeLiking"
                  @click="toggleLike"
                >
                  <svg
                    width="19" height="19" viewBox="0 0 24 24"
                    :fill="activeLiked ? 'currentColor' : 'none'"
                    stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"
                    class="transition-transform duration-300 ease-spring"
                    :class="activeLiked ? 'scale-110' : 'scale-100'"
                  >
                    <path d="M20.84 4.61a5.5 5.5 0 0 0-7.78 0L12 5.67l-1.06-1.06a5.5 5.5 0 0 0-7.78 7.78l1.06 1.06L12 21.23l7.78-7.78 1.06-1.06a5.5 5.5 0 0 0 0-7.78z" />
                  </svg>
                </button>
              </div>
            </div>
        </div>
      </div>

      <!-- Gallery: every title gets a captioned card -->
      <div
        ref="rowRef"
        class="group/rail thumb-rail mt-8 sm:mt-10 -mx-4 px-4 sm:mx-0 sm:px-0 flex gap-4 sm:gap-5 items-start overflow-x-auto scrollbar-hide pt-2 pb-4 snap-x snap-mandatory sm:fade-edge-r"
        :class="{ 'is-scrolling': thumbScrolling }"
        :data-active-index="displayIndex"
        @scroll.passive="onRowScroll"
        @pointerdown="onThumbPointerDown"
        @touchstart.passive="onThumbPointerDown"
        @wheel.passive="onThumbPointerDown"
      >
        <!-- Windowed rendering: spacers keep the scroll width exact while
             only the visible ±THUMB_BUFFER thumbnails exist in the DOM -->
        <div v-if="leadPad > 0" class="shrink-0 h-px" :style="{ width: `${leadPad}px` }" aria-hidden="true" />
        <div
          v-for="{ title, idx } in windowedTitles"
          :key="title.code"
          role="button"
          tabindex="0"
          class="group/thumb shrink-0 w-[148px] sm:w-[188px] lg:w-[212px] text-left snap-center cursor-pointer active:scale-[0.96] active:duration-100 [transition-timing-function:var(--ease-sensual)] sm:transition-transform sm:duration-300"
          :class="displayIndex === idx ? '' : 'sm:hover:-translate-y-1.5'"
          :aria-label="title.code"
          :aria-current="displayIndex === idx ? 'true' : undefined"
          @click="pickThumb(idx)"
          @keydown.enter.prevent="pickThumb(idx)"
          @keydown.space.prevent="pickThumb(idx)"
        >
          <div
            class="thumb-cover aspect-[3/2] rounded-[14px] overflow-hidden bg-fill relative"
            :class="title.magnet_status === 'dead' ? 'thumb-cover-dead' : ''"
          >
            <!-- Loading shimmer placeholder while thumbnail is decoding -->
            <div
              v-if="!isThumbReady(title.code) && !thumbErrors[title.code]"
              class="thumb-shimmer absolute inset-0 pointer-events-none"
              aria-hidden="true"
            />

            <!-- Fixed box + contain: every thumbnail gets the same height and
                 an abnormal cover (portrait, wrong dims) letterboxes inside
                 instead of stretching the rail. Never object-cover. -->
            <img
              v-if="title.cover_url && !thumbErrors[title.code]"
              :ref="(el) => bindThumbImgEl(title.code, el as HTMLImageElement | null)"
              :src="thumbSrcMap[title.code] || title.cover_thumb_url || `/api/cover/${title.code}?thumb=1`"
              :alt="title.code"
              loading="lazy"
              decoding="async"
              draggable="false"
              class="h-full w-full object-contain block select-none group-hover/thumb:scale-[1.03] transition-transform duration-500 ease-spring"
              :class="thumbImgClass(title.code)"
              @load="(e) => onThumbLoad(title.code, e)"
              @error="(e) => onThumbError(title, e)"
            />
            <div
              v-else
              class="flex h-full items-center justify-center p-2 text-center"
            >
              <span class="text-[11px] font-semibold text-foreground/50">{{ title.code }}</span>
            </div>

            <!-- Per-title like toggle (always visible when liked, revealed on hover otherwise) -->
            <button
              type="button"
              class="absolute top-2 right-2 z-10 w-7 h-7 rounded-full flex items-center justify-center backdrop-blur-md transition-all duration-200 active:scale-90"
              :class="title.user_liked
                ? 'bg-black/60 text-rose-400 opacity-100 shadow-sm'
                : 'bg-black/40 text-white/85 hover:bg-black/60 hover:text-white opacity-75 sm:opacity-0 sm:group-hover/thumb:opacity-100'"
              :aria-pressed="!!title.user_liked"
              :aria-label="title.user_liked ? `Unlike ${title.code}` : `Like ${title.code}`"
              :title="title.user_liked ? `Liked ${title.code}` : `Like ${title.code}`"
              :disabled="likingCodes.has(title.code)"
              @click.stop="toggleTitleLike(title)"
            >
              <svg
                width="13" height="13" viewBox="0 0 24 24"
                :fill="title.user_liked ? 'currentColor' : 'none'"
                stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"
              >
                <path d="M20.84 4.61a5.5 5.5 0 0 0-7.78 0L12 5.67l-1.06-1.06a5.5 5.5 0 0 0-7.78 7.78l1.06 1.06L12 21.23l7.78-7.78 1.06-1.06a5.5 5.5 0 0 0 0-7.78z" />
              </svg>
            </button>
          </div>
          <div class="mt-2.5 flex items-center gap-1.5 px-0.5 whitespace-nowrap">
            <span class="thumb-dot h-1.5 rounded-full" aria-hidden="true" />
            <span class="thumb-code text-[13px] font-semibold truncate">{{ title.code }}</span>
            <span class="ml-auto text-[12px] text-foreground-muted/70 tabular-nums">{{ shortDate(title.date) }}</span>
          </div>
        </div>
        <div v-if="trailPad > 0" class="shrink-0 h-px" :style="{ width: `${trailPad}px` }" aria-hidden="true" />
      </div>
    </div>
  </section>
</template>

<script setup lang="ts">
import type { Star, StarProfile, Title } from '~/types/api'
import { logError } from '~/composables/useLogger'
import {
  STAR_PALETTES,
  blendRgb,
  computeStarAura,
  computeTitleMood,
  getCachedCoverTint,
  rgbCss,
  sampleCoverTint,
  type Rgb,
} from '~/utils/starAura'
import {
  isThumbReady as isGlobalThumbReady,
  markThumbReady as markGlobalThumbReady,
  decodeThumbImage,
} from '~/utils/thumbCover'
import {
  heroLqipSrc,
  heroSrc,
  heroSrcset,
  heroSrcTier,
  isHeroCoverReady,
  markHeroCoverReady,
  prefetchHeroCover,
  prefetchHeroNeighbors,
} from '~/utils/heroCover'

const props = defineProps<{
  star: Star
  index?: number
}>()

const emit = defineEmits<{
  (e: 'play', magnet: string, code: string, starCode: string): void
  (e: 'deleted', code: string): void
  (e: 'social', code: string): void
}>()

const { track } = useTrack()
const { add: addLog } = useEventLog()

// ── Chromatic Persona & Desire Aura ─────────────────────────────────
const localProfile = ref<StarProfile>({ ...(props.star.profile ?? {}) })
watch(
  () => props.star.profile,
  (next) => {
    localProfile.value = { ...(next ?? {}) }
  },
)

const activeCoverTint = ref<Rgb | null>(null)
watch(
  () => props.star.titles?.[activeIndex.value]?.code,
  (code) => {
    activeCoverTint.value = code ? getCachedCoverTint(code) : null
  },
)
const starAura = computed(() =>
  computeStarAura({ ...props.star, profile: localProfile.value }),
)
const activeTitleMood = computed(() =>
  computeTitleMood(props.star.titles?.[activeIndex.value]),
)
const blendedPrimary = computed(() => {
  // Blend Star Persona + Work Style Mood + Live Cover Tint ("千人千面 · 千片千色")
  const base = activeTitleMood.value
    ? blendRgb(starAura.value.primary, activeTitleMood.value.rgb, 0.34)
    : starAura.value.primary
  return activeCoverTint.value ? blendRgb(base, activeCoverTint.value, 0.32) : base
})
const auraRgb = computed(() => rgbCss(blendedPrimary.value))
const auraDeepRgb = computed(() => rgbCss(starAura.value.deep))
const auraShimmerRgb = computed(() =>
  rgbCss(
    activeTitleMood.value
      ? blendRgb(starAura.value.shimmer, activeTitleMood.value.shimmer, 0.45)
      : starAura.value.shimmer,
  ),
)
const auraSectionStyle = computed(() => ({
  '--aura-rgb': auraRgb.value,
  '--aura-deep-rgb': auraDeepRgb.value,
  '--aura-shimmer-rgb': auraShimmerRgb.value,
}))
const auraTraitBrief = computed(() => {
  const parts: string[] = []
  if (localProfile.value.height_cm) parts.push(`${localProfile.value.height_cm}cm`)
  if (localProfile.value.cup) parts.push(`${localProfile.value.cup}`)
  return parts.join(' · ')
})

const auraOpen = ref(false)
const auraPopoverRoot = ref<HTMLElement | null>(null)
const editingProfile = ref(false)
const savingProfile = ref(false)
const profileForm = reactive<StarProfile>({
  birth_year: null,
  height_cm: null,
  cup: '',
  measurements: '',
  debut_year: null,
})

useDismiss(auraOpen, auraPopoverRoot)

function toggleAuraPanel() {
  auraOpen.value = !auraOpen.value
  if (auraOpen.value) {
    editingProfile.value = false
    profileForm.birth_year = localProfile.value.birth_year ?? null
    profileForm.height_cm = localProfile.value.height_cm ?? null
    profileForm.cup = localProfile.value.cup ?? ''
    profileForm.measurements = localProfile.value.measurements ?? ''
    profileForm.debut_year = localProfile.value.debut_year ?? starAura.value.debutYear ?? null
  }
}

async function selectPalette(paletteId: string | null) {
  const prev = localProfile.value.style ?? null
  localProfile.value = { ...localProfile.value, style: paletteId }
  try {
    const res = await $fetch<{ code: string; profile: StarProfile }>(
      `/api/stars/${encodeURIComponent(props.star.code)}/profile`,
      { method: 'PATCH', body: { ...localProfile.value, style: paletteId } },
    )
    localProfile.value = { ...(res.profile ?? localProfile.value) }
  } catch (e: any) {
    localProfile.value = { ...localProfile.value, style: prev }
    logError('star', `selectPalette ${props.star.code} failed: ${e?.message || e}`)
  }
}

async function saveProfile() {
  if (savingProfile.value) return
  savingProfile.value = true
  try {
    const payload: StarProfile = {
      birth_year: profileForm.birth_year || null,
      height_cm: profileForm.height_cm || null,
      cup: profileForm.cup?.trim().toUpperCase() || null,
      measurements: profileForm.measurements?.trim() || null,
      debut_year: profileForm.debut_year || null,
      style: localProfile.value.style ?? null,
    }
    const res = await $fetch<{ code: string; profile: StarProfile }>(
      `/api/stars/${encodeURIComponent(props.star.code)}/profile`,
      { method: 'PATCH', body: payload },
    )
    localProfile.value = { ...(res.profile ?? payload) }
    editingProfile.value = false
  } catch (e: any) {
    logError('star', `saveProfile ${props.star.code} failed: ${e?.message || e}`)
  } finally {
    savingProfile.value = false
  }
}
const { likeTitle, deleteStar } = useApi()

const id = computed(() => props.star.code.toLowerCase())
const activeIndex = ref(0)
/** Keyboard burst target — metadata leads; hero track catches up in one slide. */
const pendingIndex = ref<number | null>(null)
const displayIndex = computed(() => pendingIndex.value ?? activeIndex.value)
const activeTitle = computed(() => props.star.titles?.[displayIndex.value] || null)
const total = computed(() => props.star.titles?.length ?? 0)

const HERO_TRACK_MS = 280
const KEY_BURST_MS = 150

const heroStageRef = ref<HTMLElement | null>(null)
const heroFrameRef = ref<HTMLElement | null>(null)
const heroTrackRef = ref<HTMLElement | null>(null)
const heroSlideWidth = ref(0)

const HERO_BUFFER = 3
const HERO_IDLE_MS = 420
/** Bumps when a slide finishes decode so `isHeroCoverReady` (module Set) re-renders. */
const heroReadyTick = ref(0)

const heroWinEnd = ref(5)

function ensureHeroIndexInWindow(idx: number) {
  const n = total.value
  heroWinEnd.value = Math.max(heroWinEnd.value, Math.min(n, idx + HERO_BUFFER + 1))
}

function trimHeroWindowToIndex(idx: number) {
  const n = total.value
  heroWinEnd.value = Math.max(heroWinEnd.value, Math.min(n, idx + HERO_BUFFER + 1))
}

const windowedHeroSlides = computed(() => {
  const titles = props.star.titles ?? []
  const end = heroWinEnd.value
  return titles.slice(0, end).map((title, i) => ({ title, idx: i }))
})

const heroCellStyle = computed(() =>
  heroSlideWidth.value > 0 ? { width: `${heroSlideWidth.value}px` } : { width: '100%' },
)

const heroTrackStyle = computed(() => {
  const w = heroSlideWidth.value
  if (!w) return undefined
  const base = -activeIndex.value * w
  return { '--track-base': `${base}px` }
})

const waterWaveKey = ref(0)
const waterWaveDir = ref<'left' | 'right'>('left')
const recoilDir = ref<'left' | 'right' | null>(null)
let recoilTimer: ReturnType<typeof setTimeout> | null = null
let lastDragPx = 0

/**
 * Trigger a unidirectional horizontal recoil matching gesture direction:
 * - dir = 1 (next / swipe left): content travels left → recoil left ('left')
 * - dir = -1 (prev / swipe right): content travels right → recoil right ('right')
 */
function triggerDirectionalRecoil(dir: -1 | 1) {
  const motion: 'left' | 'right' = dir > 0 ? 'left' : 'right'
  waterWaveDir.value = motion
  waterWaveKey.value++
  recoilDir.value = null
  if (recoilTimer) clearTimeout(recoilTimer)
  requestAnimationFrame(() => {
    recoilDir.value = motion
    recoilTimer = setTimeout(() => {
      recoilDir.value = null
      recoilTimer = null
    }, 520)
  })
}

function onStageGlintMove(e: PointerEvent) {
  if (e.pointerType !== 'mouse') return
  const el = heroStageRef.value
  if (!el) return
  const rect = el.getBoundingClientRect()
  if (!rect.width || !rect.height) return
  const x = ((e.clientX - rect.left) / rect.width) * 100
  const y = ((e.clientY - rect.top) / rect.height) * 100
  el.style.setProperty('--glint-x', `${x.toFixed(1)}%`)
  el.style.setProperty('--glint-y', `${y.toFixed(1)}%`)
}

/** Compositor-only offset + liquid shear while dragging — never touches reactive state per frame. */
function setHeroDragTranslate(px: number) {
  const el = heroTrackRef.value
  if (!el) return
  if (px) {
    const vel = px - lastDragPx
    lastDragPx = px
    const skew = Math.max(-2.2, Math.min(2.2, -vel * 0.085))
    el.style.setProperty('--drag-x', `${px}px`)
    el.style.setProperty('--drag-skew', `${skew.toFixed(2)}deg`)
  } else {
    lastDragPx = 0
    el.style.removeProperty('--drag-x')
    el.style.removeProperty('--drag-skew')
  }
}

function measureHeroStage() {
  heroSlideWidth.value = heroFrameRef.value?.clientWidth ?? 0
  setHeroDragTranslate(0)
}

function heroCoverReady(code: string): boolean {
  void heroReadyTick.value
  return isHeroCoverReady(code)
}

function slideHeroImgClass(title: Title, _idx: number) {
  const ready = heroCoverReady(title.code)
  return [
    ready ? 'opacity-100' : 'opacity-0',
    ready || dragging.value ? 'duration-0' : 'transition-opacity duration-150',
  ]
}
const stepAnimLock = ref(false)
let stepAnimTimer: ReturnType<typeof setTimeout> | null = null
let keyBurstTimer: ReturnType<typeof setTimeout> | null = null
let heroPaintStart = 0
let heroPaintMeta: { code: string; cacheHit: boolean } | null = null

function armStepLock(cacheHit: boolean) {
  stepAnimLock.value = true
  if (stepAnimTimer) clearTimeout(stepAnimTimer)
  const ms = cacheHit ? HERO_TRACK_MS - 40 : HERO_TRACK_MS + 40
  stepAnimTimer = setTimeout(() => {
    stepAnimLock.value = false
    stepAnimTimer = null
  }, ms)
}

function goToIndex(
  idx: number,
  opts?: { fromChrome?: boolean; smoothThumb?: boolean; thumbAligned?: boolean },
) {
  if (idx < 0 || idx >= total.value) return
  if (idx === activeIndex.value && pendingIndex.value == null) return
  if (stepAnimLock.value && !opts?.fromChrome) return

  pendingIndex.value = null
  if (keyBurstTimer) {
    clearTimeout(keyBurstTimer)
    keyBurstTimer = null
  }

  const prevIdx = activeIndex.value
  const stepDir: -1 | 1 = idx >= prevIdx ? 1 : -1

  const title = props.star.titles?.[idx]
  const cacheHit = !!(title && isHeroCoverReady(title.code))
  if (title) {
    heroPaintStart = performance.now()
    heroPaintMeta = { code: title.code, cacheHit }
  }
  ensureHeroIndexInWindow(idx)
  activeIndex.value = idx
  setHeroDragTranslate(0)
  armStepLock(cacheHit)
  triggerDirectionalRecoil(stepDir)

  if (!opts?.thumbAligned) {
    revealThumb(idx, opts?.smoothThumb !== false ? 'smooth' : 'auto')
  }
  prefetchHeroNeighbors(props.star.titles ?? [], idx)
  if (cacheHit && title) finishHeroPaint(title)
}

function step(delta: number, opts?: { fromChrome?: boolean }) {
  const base = pendingIndex.value ?? activeIndex.value
  if (keyBurstTimer) {
    clearTimeout(keyBurstTimer)
    keyBurstTimer = null
  }
  pendingIndex.value = null
  goToIndex(base + delta, { fromChrome: opts?.fromChrome })
}

function scheduleKeyBurst(delta: -1 | 1) {
  const base = pendingIndex.value ?? activeIndex.value
  const next = Math.min(total.value - 1, Math.max(0, base + delta))
  if (next === base) return
  pendingIndex.value = next
  ensureHeroIndexInWindow(next)
  const title = props.star.titles?.[next]
  if (title) void prefetchHeroCover(title).then(() => { heroReadyTick.value++ })
  showControlsBriefly()
  if (keyBurstTimer) clearTimeout(keyBurstTimer)
  keyBurstTimer = setTimeout(flushKeyBurst, KEY_BURST_MS)
}

function flushKeyBurst() {
  keyBurstTimer = null
  const target = pendingIndex.value
  if (target == null) return
  pendingIndex.value = null
  goToIndex(target, { fromChrome: true })
}

function onHeroKeydown(e: KeyboardEvent) {
  if (e.key === 'ArrowLeft') {
    e.preventDefault()
    scheduleKeyBurst(-1)
  } else if (e.key === 'ArrowRight') {
    e.preventDefault()
    scheduleKeyBurst(1)
  }
}

const controlsShown = ref(false)
let controlsTimer: ReturnType<typeof setTimeout> | null = null

function showControlsBriefly() {
  controlsShown.value = true
  if (controlsTimer) clearTimeout(controlsTimer)
  controlsTimer = setTimeout(() => { controlsShown.value = false }, 1600)
}

function clampDrag(dx: number): number {
  return rubberBandDrag(dx, activeIndex.value <= 0, activeIndex.value >= total.value - 1)
}

const DRAG_PREFETCH_PX = 28
let dragWarmDir: -1 | 0 | 1 = 0
let heroIdleTimer: ReturnType<typeof setTimeout> | null = null

function warmHeroInDirection(dir: -1 | 1) {
  const titles = props.star.titles ?? []
  const peek = activeIndex.value + dir
  if (peek < 0 || peek >= titles.length) return
  ensureHeroIndexInWindow(peek)
  void prefetchHeroCover(titles[peek]).then(() => {
    heroReadyTick.value++
  })
}

function onHorizontalDrag(_rawDx: number, clampedDx: number) {
  if (Math.abs(clampedDx) < DRAG_PREFETCH_PX) return
  const dir: -1 | 1 = clampedDx < 0 ? 1 : -1
  if (dragWarmDir === dir) return
  dragWarmDir = dir
  warmHeroInDirection(dir)
}

function onWheelAccumulate(acc: number) {
  if (Math.abs(acc) < 36) return
  warmHeroInDirection(acc > 0 ? 1 : -1)
}

function onHeroPointerDown(e: PointerEvent) {
  const el = heroTrackRef.value
  if (el) {
    el.classList.remove('hero-track-anim')
  }
  onPointerDown(e)
}

function onHeroDragRelease({
  dir,
  done,
}: {
  dx: number
  clampedDx: number
  dt: number
  dir: number | null
  done: () => void
}) {
  const el = heroTrackRef.value
  const w = heroSlideWidth.value
  const curIdx = activeIndex.value
  let targetIdx = curIdx
  if (dir !== null && dir !== 0) {
    targetIdx = Math.min(total.value - 1, Math.max(0, curIdx + dir))
  }
  const canCommit = targetIdx !== curIdx

  ensureHeroIndexInWindow(targetIdx)

  if (el && w) {
    const targetBase = -targetIdx * w
    el.classList.add('hero-track-anim')
    el.style.setProperty('--track-base', `${targetBase}px`)
    el.style.removeProperty('--drag-x')
  }

  if (canCommit) {
    goToIndex(targetIdx, { fromChrome: true, smoothThumb: true })
    showControlsBriefly()
  }

  done()
}

const {
  dragging,
  onPointerDown,
  onPointerMove,
  onPointerUp,
  onPointerCancel,
  onWheel,
} = useHeroStepGesture({
  canStep: () => total.value > 1 && !stepAnimLock.value,
  canDrag: () => total.value > 1,
  stageWidth: () => heroStageRef.value?.clientWidth ?? 360,
  clampDx: clampDrag,
  onStep: (delta) => step(delta),
  onShowControls: showControlsBriefly,
  setDragTranslate: setHeroDragTranslate,
  onHorizontalDrag,
  onWheelAccumulate,
  onDragRelease: onHeroDragRelease,
})

watch(dragging, (isDragging) => {
  if (isDragging) return
  dragWarmDir = 0
  if (heroIdleTimer) clearTimeout(heroIdleTimer)
  heroIdleTimer = setTimeout(() => trimHeroWindowToIndex(activeIndex.value), HERO_IDLE_MS)
})

function bindHeroImgEl(title: Title, el: HTMLImageElement | null) {
  if (!el?.complete || el.naturalWidth <= 0) return
  if (isHeroCoverReady(title.code)) return
  void onHeroSlideLoad(title, { target: el } as Event)
}

let thumbUserInteracting = false
let programmaticThumbUntil = 0

function onThumbPointerDown() {
  thumbUserInteracting = true
}

function thumbIndexAtScroll(left: number): number {
  if (!thumbStride.value) return activeIndex.value
  const row = rowRef.value
  if (!row) return activeIndex.value
  const maxScroll = Math.max(0, row.scrollWidth - row.clientWidth)
  // At the start of the rail, the first item is selected
  if (left <= 20) return 0
  // At the end of the rail, the last item is selected
  if (maxScroll > 0 && left >= maxScroll - 20) return total.value - 1

  const center = left + (rowViewWidth.value - thumbItemWidth.value) / 2
  const idx = Math.round(center / thumbStride.value)
  return Math.min(total.value - 1, Math.max(0, idx))
}

/** Keep the active thumb centered; flag suppresses hero feedback while programmatic. */
function revealThumb(idx: number, behavior: ScrollBehavior = 'smooth') {
  ensureThumbIndexInWindow(idx)
  const row = rowRef.value
  if (!row || !thumbStride.value) return
  const left = idx * thumbStride.value - (row.clientWidth - thumbItemWidth.value) / 2
  thumbUserInteracting = false
  programmaticThumbUntil = Date.now() + 600
  row.scrollTo({ left: Math.max(0, left), behavior })
}

function syncHeroFromThumbScroll() {
  if (Date.now() < programmaticThumbUntil || !thumbUserInteracting || pendingIndex.value != null || dragging.value) return
  thumbUserInteracting = false
  const row = rowRef.value
  if (!row || !thumbStride.value) return
  const idx = thumbIndexAtScroll(row.scrollLeft)
  if (idx !== activeIndex.value) {
    goToIndex(idx, { fromChrome: true, thumbAligned: true })
  }
}

const heroErrors = ref<Record<string, boolean>>({})
const thumbErrors = ref<Record<string, boolean>>({})
const thumbReadyTick = ref(0)
const thumbSrcMap = reactive<Record<string, string>>({})
const thumbFallbackTries = reactive<Record<string, boolean>>({})

function isThumbReady(code: string): boolean {
  void thumbReadyTick.value
  return isGlobalThumbReady(code)
}

function thumbImgClass(code: string) {
  const ready = isThumbReady(code)
  return [
    ready ? 'opacity-100' : 'opacity-0',
    ready ? 'duration-0' : 'transition-opacity duration-300 ease-spring',
  ]
}

async function onThumbLoad(code: string, e: Event) {
  const img = e.target as HTMLImageElement
  const ok = await decodeThumbImage(img)
  if (ok) {
    markGlobalThumbReady(code)
    thumbReadyTick.value++
  }
}

function bindThumbImgEl(code: string, el: HTMLImageElement | null) {
  if (!el?.complete || el.naturalWidth <= 0) return
  if (isGlobalThumbReady(code)) return
  void decodeThumbImage(el).then((ok) => {
    if (ok) {
      markGlobalThumbReady(code)
      thumbReadyTick.value++
    }
  })
}

function onThumbError(title: Title, e: Event) {
  const code = title.code
  const img = e.target as HTMLImageElement
  const fallback = `/api/cover/${code}?thumb=1`
  if (!thumbFallbackTries[code] && !img.src.includes(`/api/cover/${code}`)) {
    thumbFallbackTries[code] = true
    thumbSrcMap[code] = fallback
    img.src = fallback
    return
  }
  thumbErrors.value[code] = true
}

function finishHeroPaint(t: Title) {
  if (!heroPaintMeta || heroPaintMeta.code !== t.code) return
  const paint_ms = Math.round(performance.now() - heroPaintStart)
  track('hero_step', {
    code: t.code,
    star_code: props.star.code,
    meta: {
      paint_ms,
      cache_hit: heroPaintMeta.cacheHit,
      src_tier: heroSrcTier(t),
    },
  })
  heroPaintMeta = null
}

async function onHeroSlideLoad(t: Title, e: Event) {
  const img = e.target as HTMLImageElement
  try {
    if (typeof img.decode === 'function') await img.decode()
  } catch {
    // Truncated or unsupported — still show if pixels landed.
  }
  markHeroCoverReady(t.code)
  heroReadyTick.value++
  if (activeTitle.value?.code === t.code) {
    finishHeroPaint(t)
    // Defer offscreen canvas color sampling until idle so it never blocks first paint.
    const sample = () => {
      const sampled = sampleCoverTint(t.code, img)
      if (sampled && activeTitle.value?.code === t.code) {
        activeCoverTint.value = sampled
      }
    }
    if (typeof window !== 'undefined' && 'requestIdleCallback' in window) {
      ;(window as any).requestIdleCallback(sample, { timeout: 300 })
    } else {
      setTimeout(sample, 32)
    }
  }
}

function pickThumb(idx: number) {
  if (idx === displayIndex.value) return
  goToIndex(idx, { fromChrome: true, smoothThumb: true })
}

const activeIsHd = computed(() => {
  const t = activeTitle.value
  if (!t || t.magnet_status === 'dead') return false
  const res = t.resolution?.toLowerCase() ?? ''
  return res.includes('1080') || res.includes('4k')
})

// ── Thumbnail row windowing ──────────────────────────────────────────
// A star can have ~100 titles; mounting every button+img keeps thousands of
// DOM nodes alive after a full-catalog scroll. Render only the visible
// window (±THUMB_BUFFER) and pad with spacers so the scroll width (and snap
// positions) stay exactly as if every item were present.
const THUMB_BUFFER = 8
const THUMB_IDLE_MS = 380
const thumbScrolling = ref(false)
const rowRef = ref<HTMLElement | null>(null)
const rowViewWidth = ref(0)
const thumbItemWidth = ref(0)
const thumbGap = ref(0)
const thumbStride = computed(() => thumbItemWidth.value + thumbGap.value)
const thumbWinStart = ref(0)
const thumbWinEnd = ref(20)

const windowedTitles = computed(() => {
  const titles = props.star.titles ?? []
  return titles.slice(thumbWinStart.value, thumbWinEnd.value).map((title, i) => ({
    title,
    idx: thumbWinStart.value + i,
  }))
})

// Spacer widths must reproduce the flex layout exactly: N hidden items occupy
// N*width + (N-1)*gap; the spacer itself adds one more gap back.
const leadPad = computed(() => {
  const start = thumbWinStart.value
  return start > 0 && thumbStride.value ? start * thumbStride.value - thumbGap.value : 0
})
const trailPad = computed(() => {
  const totalN = props.star.titles?.length ?? 0
  const remaining = totalN - thumbWinEnd.value
  return remaining > 0 && thumbStride.value
    ? remaining * thumbStride.value - thumbGap.value
    : 0
})

function initThumbWindow() {
  const totalN = props.star.titles?.length ?? 0
  if (!thumbStride.value || !rowViewWidth.value) {
    thumbWinEnd.value = Math.min(totalN, 10)
    return
  }
  const visible = Math.ceil(rowViewWidth.value / thumbStride.value)
  thumbWinEnd.value = Math.min(totalN, visible + THUMB_BUFFER * 2)
}

function ensureThumbIndexInWindow(idx: number) {
  const totalN = props.star.titles?.length ?? 0
  if (idx < thumbWinStart.value) {
    thumbWinStart.value = Math.max(0, idx - THUMB_BUFFER)
  }
  if (idx >= thumbWinEnd.value) {
    thumbWinEnd.value = Math.min(totalN, idx + THUMB_BUFFER + 1)
  }
}

function expandThumbWindowFromScroll() {
  const row = rowRef.value
  if (!row || !thumbStride.value) return
  const totalN = props.star.titles?.length ?? 0
  const left = row.scrollLeft
  const firstVisible = Math.floor(left / thumbStride.value)
  const visible = Math.ceil(rowViewWidth.value / thumbStride.value)
  const needStart = Math.max(0, firstVisible - THUMB_BUFFER)
  const needEnd = Math.min(totalN, firstVisible + visible + THUMB_BUFFER)
  if (needStart < thumbWinStart.value) thumbWinStart.value = needStart
  if (needEnd > thumbWinEnd.value) thumbWinEnd.value = needEnd
}

function trimThumbWindowToViewport() {
  const row = rowRef.value
  if (!row || !thumbStride.value) return
  const totalN = props.star.titles?.length ?? 0
  const left = row.scrollLeft
  const firstVisible = Math.floor(left / thumbStride.value)
  const visible = Math.ceil(rowViewWidth.value / thumbStride.value)
  let start = Math.max(0, firstVisible - THUMB_BUFFER)
  let end = Math.min(totalN, firstVisible + visible + THUMB_BUFFER)
  const idx = activeIndex.value
  start = Math.min(start, Math.max(0, idx - THUMB_BUFFER))
  end = Math.max(end, Math.min(totalN, idx + THUMB_BUFFER + 1))
  thumbWinStart.value = start
  thumbWinEnd.value = end
}

let rowScrollRaf = 0
let thumbScrollIdleTimer: ReturnType<typeof setTimeout> | null = null
function onRowScroll() {
  thumbScrolling.value = true
  if (rowScrollRaf) return
  rowScrollRaf = requestAnimationFrame(() => {
    rowScrollRaf = 0
    expandThumbWindowFromScroll()
  })
  if (thumbScrollIdleTimer) clearTimeout(thumbScrollIdleTimer)
  thumbScrollIdleTimer = setTimeout(() => {
    thumbScrolling.value = false
    trimThumbWindowToViewport()
    syncHeroFromThumbScroll()
  }, THUMB_IDLE_MS)
}

let rowResizeObserver: ResizeObserver | null = null
let heroResizeObserver: ResizeObserver | null = null

function measureRow() {
  const row = rowRef.value
  if (!row) return
  rowViewWidth.value = row.clientWidth
  const firstBtn = row.querySelector('button')
  if (firstBtn) {
    thumbItemWidth.value = (firstBtn as HTMLElement).offsetWidth
    thumbGap.value = parseFloat(getComputedStyle(row).columnGap) || 0
  }
  initThumbWindow()
}

onMounted(() => {
  trimHeroWindowToIndex(activeIndex.value)
  measureHeroStage()
  measureRow()
  if (heroFrameRef.value) {
    heroResizeObserver = new ResizeObserver(measureHeroStage)
    heroResizeObserver.observe(heroFrameRef.value)
  }
  if (rowRef.value) {
    rowResizeObserver = new ResizeObserver(measureRow)
    rowResizeObserver.observe(rowRef.value)
  }
  prefetchHeroNeighbors(props.star.titles ?? [], activeIndex.value)
})

onUnmounted(() => {
  rowResizeObserver?.disconnect()
  heroResizeObserver?.disconnect()
  if (rowScrollRaf) cancelAnimationFrame(rowScrollRaf)
  if (thumbScrollIdleTimer) clearTimeout(thumbScrollIdleTimer)
  if (heroIdleTimer) clearTimeout(heroIdleTimer)
  if (keyBurstTimer) clearTimeout(keyBurstTimer)
  if (controlsTimer) clearTimeout(controlsTimer)
  if (stepAnimTimer) clearTimeout(stepAnimTimer)
  if (recoilTimer) clearTimeout(recoilTimer)
})
const copied = ref(false)
const likingCodes = ref<Set<string>>(new Set())
const activeLiking = computed(() => !!activeTitle.value && likingCodes.value.has(activeTitle.value.code))
const activeLiked = computed(() => activeTitle.value?.user_liked ?? false)
const activePlayable = computed(() =>
  !!activeTitle.value?.magnet && activeTitle.value?.magnet_status !== 'dead'
)

watch(() => props.star.titles, (titles, prev) => {
  // Full-catalog refetches (sync.completed / star.ready / resync) replace
  // the titles array; keep the user's picked thumbnail if it still exists
  // instead of snapping every row back to #1 and reloading the hero image.
  const current = prev?.[activeIndex.value]?.code
  const kept = current ? titles?.findIndex(t => t.code === current) : -1
  activeIndex.value = kept != null && kept >= 0 ? kept : 0
})

watch(activeIndex, (idx) => {
  ensureHeroIndexInWindow(idx)
  prefetchHeroNeighbors(props.star.titles ?? [], idx)
})

watch(() => activeTitle.value?.code, (code) => {
  if (!code) return
  const t = activeTitle.value
  if (!t) return
  if (!isHeroCoverReady(code)) prefetchHeroCover(t)
  if (!heroPaintMeta || heroPaintMeta.code !== code) {
    heroPaintStart = performance.now()
    heroPaintMeta = { code, cacheHit: isHeroCoverReady(code) }
  }
})

function onPlay() {
  if (!activePlayable.value) return
  track('play', { code: activeTitle.value.code, star_code: props.star.code })
  addLog({ kind: 'action', title: `Play ${activeTitle.value.code}`, detail: props.star.name, state: 'info' })
  emit('play', activeTitle.value.magnet!, activeTitle.value.code, props.star.code)
}

const justLiked = ref(false)
let likeAnimTimer: ReturnType<typeof setTimeout> | null = null

async function toggleTitleLike(target: Title | undefined) {
  if (!target || likingCodes.value.has(target.code)) return
  const nextSet = new Set(likingCodes.value)
  nextSet.add(target.code)
  likingCodes.value = nextSet
  const prevVal = !!target.user_liked
  const newVal = !prevVal
  // Optimistic toggle so the heart responds immediately; roll back on error.
  target.user_liked = newVal
  if (newVal && target.code === activeTitle.value?.code) {
    justLiked.value = true
    if (likeAnimTimer) clearTimeout(likeAnimTimer)
    likeAnimTimer = setTimeout(() => { justLiked.value = false }, 600)
  }
  try {
    await likeTitle(target.code, newVal)
    track(newVal ? 'like' : 'unlike', { code: target.code, star_code: props.star.code })
    addLog({ kind: 'action', title: `${newVal ? 'Liked' : 'Unliked'} ${target.code}`, detail: props.star.name, state: 'success' })
  } catch (e: any) {
    target.user_liked = prevVal
    justLiked.value = false
    const msg = String(e?.data?.detail ?? e?.message ?? e)
    console.error('like failed:', e)
    logError('like', `toggleLike ${target.code} (${newVal}) failed: ${msg}`)
    addLog({ kind: 'action', title: `Like failed: ${target.code}`, detail: msg, state: 'error' })
  } finally {
    const doneSet = new Set(likingCodes.value)
    doneSet.delete(target.code)
    likingCodes.value = doneSet
  }
}

async function toggleLike() {
  await toggleTitleLike(activeTitle.value)
}

function copyMagnet() {
  const magnet = activeTitle.value?.magnet
  if (!magnet) return
  navigator.clipboard.writeText(magnet).then(() => {
    copied.value = true
    setTimeout(() => copied.value = false, 1500)
    track('copy_magnet', { code: activeTitle.value?.code, star_code: props.star.code, meta: { source: 'hero' } })
  }).catch(() => {
    // ignore
  })
}

const deleting = ref(false)

async function onDelete() {
  if (!confirm(`Delete star "${props.star.name}" and all associated title data?\n(Cache files will be preserved)`)) {
    return
  }
  deleting.value = true
  try {
    await deleteStar(props.star.code)
    emit('deleted', props.star.code)
  } catch (e: any) {
    alert(e?.message || 'Delete failed')
  } finally {
    deleting.value = false
  }
}

function shortDate(dateStr?: string): string {
  const parts = dateStr?.split('/')
  if (!parts || parts.length !== 3) return ''
  return `${parts[2].slice(2)}.${parts[1].padStart(2, '0')}.${parts[0].padStart(2, '0')}`
}

function fmtDate(dateStr?: string): string {
  if (!dateStr) return ''
  const parts = dateStr.split('/')
  if (parts.length === 3) {
    return `${parts[2]}-${parts[1].padStart(2, '0')}-${parts[0].padStart(2, '0')}`
  }
  return dateStr
}
</script>
