/**
 * starAura — Chromatic Persona & Desire Aura engine.
 *
 * Maps a star's real traits (age, height, silhouette/cup, career span, catalog depth)
 * plus an optional subtle live tint from the active cover into a refined Apple-grade
 * editorial color signature (`--aura-rgb`, `--aura-deep-rgb`).
 */

import type { Star, StarProfile } from '~/types/api'

export interface Rgb {
  r: number
  g: number
  b: number
}

export interface StarAura {
  /** Primary chromatic signature RGB. */
  primary: Rgb
  /** Deeper shadow/velvet companion RGB. */
  deep: Rgb
  /** Poetic mood archetype name. */
  label: string
  /** Short evocative descriptor connecting color to persona/desire. */
  mood: string
  /** Derived or configured career span in years (null if no dated titles). */
  careerYears: number | null
  /** Earliest known work year. */
  debutYear: number | null
  /** Derived age from `profile.birth_year` if present. */
  age: number | null
}

const CURRENT_YEAR = new Date().getFullYear()

function hashString(s: string): number {
  let h = 2166136261
  for (let i = 0; i < s.length; i++) {
    h ^= s.charCodeAt(i)
    h = Math.imul(h, 16777619)
  }
  return Math.abs(h)
}

function clamp(v: number, lo: number, hi: number): number {
  return Math.min(hi, Math.max(lo, v))
}

function hslToRgb(hDeg: number, sPct: number, lPct: number): Rgb {
  const h = (((hDeg % 360) + 360) % 360) / 360
  const s = clamp(sPct, 0, 100) / 100
  const l = clamp(lPct, 0, 100) / 100
  if (s === 0) {
    const v = Math.round(l * 255)
    return { r: v, g: v, b: v }
  }
  const q = l < 0.5 ? l * (1 + s) : l + s - l * s
  const p = 2 * l - q
  const hue2rgb = (t: number) => {
    let tt = t
    if (tt < 0) tt += 1
    if (tt > 1) tt -= 1
    if (tt < 1 / 6) return p + (q - p) * 6 * tt
    if (tt < 1 / 2) return q
    if (tt < 2 / 3) return p + (q - p) * (2 / 3 - tt) * 6
    return p
  }
  return {
    r: Math.round(hue2rgb(h + 1 / 3) * 255),
    g: Math.round(hue2rgb(h) * 255),
    b: Math.round(hue2rgb(h - 1 / 3) * 255),
  }
}

export function rgbCss(c: Rgb): string {
  return `${c.r}, ${c.g}, ${c.b}`
}

export function blendRgb(a: Rgb, b: Rgb, bWeight: number): Rgb {
  const w = clamp(bWeight, 0, 1)
  const aw = 1 - w
  return {
    r: Math.round(a.r * aw + b.r * w),
    g: Math.round(a.g * aw + b.g * w),
    b: Math.round(a.b * aw + b.b * w),
  }
}

function parseCupRank(cup?: string | null): number {
  if (!cup) return 0
  const ch = cup.trim().toUpperCase().charCodeAt(0)
  if (ch >= 65 && ch <= 75) return ch - 64 // A=1 .. K=11
  return 0
}

function deriveDebutYear(star: Star): number | null {
  if (star.profile?.debut_year && star.profile.debut_year > 1990) {
    return star.profile.debut_year
  }
  let earliest = Infinity
  for (const t of star.titles ?? []) {
    const raw = t.release_date_sort || t.date || ''
    const m = raw.match(/(20\d{2}|19\d{2})/)
    if (m) {
      const y = Number(m[1])
      if (y >= 1995 && y <= CURRENT_YEAR + 1 && y < earliest) {
        earliest = y
      }
    }
  }
  return Number.isFinite(earliest) ? earliest : null
}

/**
 * Compute a star's personal chromatic aura from her profile & career experience.
 */
export function computeStarAura(star: Star): StarAura {
  const profile: StarProfile = star.profile ?? {}
  const debutYear = deriveDebutYear(star)
  const careerYears = debutYear ? Math.max(1, CURRENT_YEAR - debutYear + 1) : null
  const age =
    profile.birth_year && profile.birth_year > 1965 && profile.birth_year < CURRENT_YEAR
      ? CURRENT_YEAR - profile.birth_year
      : null
  const height = profile.height_cm ?? null
  const cupRank = parseCupRank(profile.cup)
  const titleCount = star.titles?.length ?? 0
  const likedCount = (star.titles ?? []).filter((t) => t.user_liked).length

  // Subtle deterministic harmonic per star (+/- 6 deg) so every shelf feels unique.
  const seed = hashString(`${star.code}:${star.name}`)
  const jitter = (seed % 13) - 6

  // Archetype selection from real traits (age, height, silhouette, career span)
  let baseHue = 348
  let sat = 74
  let light = 50
  let label = 'Rose Silk'
  let mood = 'Delicate warmth & translucent allure'

  if ((age !== null && age >= 28) || (careerYears !== null && careerYears >= 6)) {
    // Veteran / Mature: Burgundy Wine
    baseHue = 330
    sat = 64
    light = 43
    label = 'Velvet Wine'
    mood = 'Nocturnal depth & seasoned poise'
  } else if (height !== null && height >= 166) {
    // Statuesque / Tall: Champagne Amber
    baseHue = 22
    sat = 68
    light = 48
    label = 'Champagne Gold'
    mood = 'Statuesque warmth & editorial glow'
  } else if (cupRank >= 6 || (titleCount >= 45 && careerYears !== null && careerYears <= 5)) {
    // Bold / Curvy / Iconic presence: Crimson Velvet
    baseHue = 353
    sat = 80
    light = 49
    label = 'Crimson Velvet'
    mood = 'Magnetic intensity & unmistakable desire'
  } else if ((age !== null && age <= 23) || (careerYears !== null && careerYears <= 2)) {
    // Fresh debut / Youthful: Rose Blush
    baseHue = 344
    sat = 78
    light = 54
    label = 'Blush Rose'
    mood = 'Fresh pulse & luminous skin warmth'
  } else {
    // Mid-career muse: Orchid Dusk (or Rose Silk via harmonic)
    if (seed % 2 === 0) {
      baseHue = 312
      sat = 58
      light = 46
      label = 'Orchid Dusk'
      mood = 'Silk tension & quiet magnetism'
    } else {
      baseHue = 348
      sat = 72
      light = 50
      label = 'Rose Silk'
      mood = 'Effortless grace & warm allure'
    }
  }

  // Fine-tune chroma & depth by silhouette, liked affinity, and stature.
  if (cupRank >= 5) sat = clamp(sat + Math.min(10, (cupRank - 4) * 2), 45, 88)
  if (likedCount > 0) sat = clamp(sat + Math.min(8, likedCount * 2), 45, 90)
  if (height !== null && height >= 164) light = clamp(light + 2, 38, 56)

  const hue = baseHue + jitter
  const primary = hslToRgb(hue, sat, light)
  const deep = hslToRgb(hue - 8, clamp(sat - 6, 35, 85), clamp(light - 14, 24, 42))

  return {
    primary,
    deep,
    label,
    mood,
    careerYears,
    debutYear,
    age,
  }
}

const coverTintCache = new Map<string, Rgb>()

/** Return a previously sampled cover tint if cached, without touching the DOM. */
export function getCachedCoverTint(code: string): Rgb | null {
  return coverTintCache.get(code) ?? null
}

/**
 * Sample a subtle dominant warm/accent tint from a decoded cover image once,
 * cached by `code`. Safe against CORS taint and zero-cost after first decode.
 */
export function sampleCoverTint(code: string, img: HTMLImageElement): Rgb | null {
  const cached = coverTintCache.get(code)
  if (cached) return cached
  if (typeof document === 'undefined' || !img.complete || img.naturalWidth === 0) return null

  try {
    const canvas = document.createElement('canvas')
    canvas.width = 12
    canvas.height = 12
    const ctx = canvas.getContext('2d', { willReadFrequently: true })
    if (!ctx) return null
    ctx.drawImage(img, 0, 0, 12, 12)
    const data = ctx.getImageData(0, 0, 12, 12).data

    let rSum = 0
    let gSum = 0
    let bSum = 0
    let wSum = 0

    for (let i = 0; i < data.length; i += 4) {
      const r = data[i]
      const g = data[i + 1]
      const b = data[i + 2]
      const max = Math.max(r, g, b)
      const min = Math.min(r, g, b)
      const chroma = max - min
      const lum = (max + min) / 2
      // Skip near-white/near-black paper edges; weight saturated mid-tones higher
      if (lum < 28 || lum > 235) continue
      const weight = 0.25 + (chroma / 255) * 2.5
      rSum += r * weight
      gSum += g * weight
      bSum += b * weight
      wSum += weight
    }

    if (wSum <= 0) return null
    const rgb: Rgb = {
      r: clamp(Math.round(rSum / wSum), 35, 225),
      g: clamp(Math.round(gSum / wSum), 25, 200),
      b: clamp(Math.round(bSum / wSum), 35, 215),
    }
    coverTintCache.set(code, rgb)
    return rgb
  } catch {
    return null
  }
}
