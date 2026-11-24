/**
 * starAura — Chromatic Persona & Desire Aura engine ("千人千面").
 *
 * Maps each star's traits (age, height, silhouette/cup, career span, catalog depth)
 * plus a deterministic personal harmonic across 10 curated luxury editorial palettes,
 * blended smoothly with a live dominant tint sampled from the active cover.
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
  /** Soft sunlit highlight RGB for water-caustic reflections. */
  shimmer: Rgb
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

interface PaletteDef {
  hue: number
  sat: number
  light: number
  label: string
  mood: string
}

const PALETTES: PaletteDef[] = [
  { hue: 350, sat: 82, light: 50, label: 'Crimson Velvet', mood: 'Magnetic intensity & unmistakable desire' },
  { hue: 326, sat: 68, light: 42, label: 'Velvet Wine', mood: 'Nocturnal depth & seasoned poise' },
  { hue: 24, sat: 76, light: 48, label: 'Champagne Amber', mood: 'Statuesque golden-hour warmth' },
  { hue: 342, sat: 80, light: 55, label: 'Blush Rose', mood: 'Fresh pulse & luminous skin warmth' },
  { hue: 288, sat: 64, light: 48, label: 'Orchid Silk', mood: 'Silk tension & nocturnal allure' },
  { hue: 8, sat: 80, light: 52, label: 'Coral Sunset', mood: 'Radiant warmth & sunlit magnetism' },
  { hue: 214, sat: 72, light: 48, label: 'Sapphire Dusk', mood: 'Crystalline poise & cool mystery' },
  { hue: 164, sat: 70, light: 38, label: 'Emerald Noir', mood: 'Rare jewel-toned elegance' },
  { hue: 262, sat: 66, light: 50, label: 'Plum Mirage', mood: 'Amethyst depth & quiet seduction' },
  { hue: 38, sat: 78, light: 46, label: 'Gilded Honey', mood: 'Sunlit nectar & effortless warmth' },
]

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
 * Compute a star's unmistakable personal chromatic aura ("千人千面").
 *
 * Explicit profile traits (age, height, cup, debut) steer her into the matching
 * emotional archetype; stars without explicit profiles spread organically across
 * all 10 curated palettes weighted by career span & catalog energy.
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
  const likedCount = (star.titles ?? []).filter((t) => t.user_liked).length

  const seed = hashString(`${star.code}:${star.name}`)
  const jitter = (seed % 17) - 8

  let chosen: PaletteDef
  if (height !== null && height >= 166) {
    // Tall / statuesque -> Champagne Amber or Gilded Honey
    chosen = seed % 2 === 0 ? PALETTES[2] : PALETTES[9]
  } else if (cupRank >= 6) {
    // Curvy / high-presence -> Crimson Velvet or Coral Sunset
    chosen = seed % 2 === 0 ? PALETTES[0] : PALETTES[5]
  } else if (age !== null && age >= 28) {
    // Mature -> Velvet Wine or Plum Mirage
    chosen = seed % 2 === 0 ? PALETTES[1] : PALETTES[8]
  } else if (age !== null && age <= 23) {
    // Youthful -> Blush Rose or Coral Sunset
    chosen = seed % 2 === 0 ? PALETTES[3] : PALETTES[5]
  } else if (careerYears !== null && careerYears >= 6) {
    // Veteran catalog -> Velvet Wine, Orchid Silk, Sapphire Dusk, Emerald Noir, Plum Mirage
    const veteranPool = [PALETTES[1], PALETTES[4], PALETTES[6], PALETTES[7], PALETTES[8]]
    chosen = veteranPool[seed % veteranPool.length]
  } else if (careerYears !== null && careerYears <= 2) {
    // New generation -> Blush Rose, Coral Sunset, Champagne Amber, Gilded Honey
    const freshPool = [PALETTES[3], PALETTES[5], PALETTES[2], PALETTES[9]]
    chosen = freshPool[seed % freshPool.length]
  } else {
    // Full 10-palette editorial diversity
    chosen = PALETTES[seed % PALETTES.length]
  }

  let sat = chosen.sat
  let light = chosen.light
  if (cupRank >= 5) sat = clamp(sat + Math.min(10, (cupRank - 4) * 2), 48, 90)
  if (likedCount > 0) sat = clamp(sat + Math.min(8, likedCount * 2), 48, 92)
  if (height !== null && height >= 164) light = clamp(light + 2, 36, 58)

  const hue = chosen.hue + jitter
  const primary = hslToRgb(hue, sat, light)
  const deep = hslToRgb(hue - 10, clamp(sat - 4, 38, 88), clamp(light - 14, 22, 42))
  const shimmer = hslToRgb(hue + 14, clamp(sat + 6, 55, 96), clamp(light + 22, 66, 82))

  return {
    primary,
    deep,
    shimmer,
    label: chosen.label,
    mood: chosen.mood,
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
      if (lum < 24 || lum > 238) continue
      const weight = 0.2 + (chroma / 255) * 3.0
      rSum += r * weight
      gSum += g * weight
      bSum += b * weight
      wSum += weight
    }

    if (wSum <= 0) return null
    const rgb: Rgb = {
      r: clamp(Math.round(rSum / wSum), 30, 232),
      g: clamp(Math.round(gSum / wSum), 24, 210),
      b: clamp(Math.round(bSum / wSum), 32, 224),
    }
    coverTintCache.set(code, rgb)
    return rgb
  } catch {
    return null
  }
}
