import type { Title } from '~/types/api'

/** Instant LQIP while the mid hero decodes. */
export function heroLqipSrc(t: Title): string | null {
  if (t.cover_thumb_url) return t.cover_thumb_url
  return null
}

/** Smallest hero URL that still covers the ~760px stage (mid > thumb > full). */
export function heroSrc(t: Title): string {
  if (t.cover_mid_url) return t.cover_mid_url
  if (t.cover_thumb_url) return t.cover_thumb_url
  if (t.cover_url) return t.cover_url
  return `/api/cover/${t.code}`
}

export function heroSrcTier(t: Title): 'mid' | 'thumb' | 'full' | 'api' {
  if (t.cover_mid_url) return 'mid'
  if (t.cover_thumb_url) return 'thumb'
  if (t.cover_url?.startsWith('/images/')) return 'full'
  return 'api'
}

export function heroSrcset(t: Title): string | undefined {
  const candidates: string[] = []
  if (t.cover_thumb_url) candidates.push(`${t.cover_thumb_url} 400w`)
  if (t.cover_mid_url) candidates.push(`${t.cover_mid_url} 800w`)
  if (t.cover_url && t.cover_url.startsWith('/images/')) {
    candidates.push(`${t.cover_url} ${t.cover_w || 1600}w`)
  }
  return candidates.length > 1 ? candidates.join(', ') : undefined
}

const ready = new Set<string>()
const inflight = new Map<string, Promise<void>>()

export function isHeroCoverReady(code: string): boolean {
  return ready.has(code.toUpperCase())
}

export function markHeroCoverReady(code: string) {
  ready.add(code.toUpperCase())
}

function prefetchUrl(url: string) {
  const img = new Image()
  img.decoding = 'async'
  img.src = url
}

function prefetchHeroCoverMid(t: Title): Promise<void> {
  const code = t.code.toUpperCase()
  if (ready.has(code)) return Promise.resolve()
  const existing = inflight.get(code)
  if (existing) return existing

  const url = heroSrc(t)
  const p = new Promise<void>((resolve) => {
    const img = new Image()
    img.decoding = 'async'
    img.src = url
    const done = () => {
      ready.add(code)
      inflight.delete(code)
      resolve()
    }
    img.onload = () => {
      if (typeof img.decode === 'function') {
        img.decode().then(done).catch(done)
      } else {
        done()
      }
    }
    img.onerror = () => {
      inflight.delete(code)
      resolve()
    }
  })
  inflight.set(code, p)
  return p
}

/** Warm thumb first (instant LQIP), then mid/full decode cache. */
export function prefetchHeroCover(t: Title | null | undefined): Promise<void> {
  if (!t?.code) return Promise.resolve()
  const lqip = heroLqipSrc(t)
  if (lqip) prefetchUrl(lqip)
  return prefetchHeroCoverMid(t)
}

export function prefetchHeroNeighbors(titles: Title[], index: number, radius = 3) {
  if (!titles.length) return
  prefetchHeroCover(titles[index])
  for (let d = 1; d <= radius; d++) {
    prefetchHeroCover(titles[index - d])
    prefetchHeroCover(titles[index + d])
  }
}
