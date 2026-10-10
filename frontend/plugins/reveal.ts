/**
 * v-reveal — one-shot scroll reveal (see `.reveal` in main.css).
 *
 *   <div v-reveal>…</div>          reveal when 12% visible
 *   <div v-reveal="0.08">…</div>   same, delayed 80ms (stagger siblings)
 *
 * SSR renders the element in its final state (no `.reveal` class), so
 * content is never hidden when JS is slow or absent. Elements already in
 * the viewport at mount still animate in.
 */
import type { Directive } from 'vue'

let observer: IntersectionObserver | null = null

function getObserver(): IntersectionObserver {
  if (!observer) {
    observer = new IntersectionObserver((entries) => {
      for (const entry of entries) {
        if (!entry.isIntersecting) continue
        entry.target.classList.add('is-revealed')
        observer!.unobserve(entry.target)
      }
    }, { threshold: 0.12, rootMargin: '0px 0px -6% 0px' })
  }
  return observer
}

const reveal: Directive<HTMLElement, number | undefined> = {
  getSSRProps: () => ({}),
  mounted(el, binding) {
    if (typeof binding.value === 'number') {
      el.style.setProperty('--reveal-delay', `${binding.value}s`)
    }
    el.classList.add('reveal')
    getObserver().observe(el)
  },
  unmounted(el) {
    observer?.unobserve(el)
  },
}

export default defineNuxtPlugin((nuxtApp) => {
  nuxtApp.vueApp.directive('reveal', reveal)
})
