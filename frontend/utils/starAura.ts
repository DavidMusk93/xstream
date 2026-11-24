/**
 * starAura — Chromatic Persona & Per-Work Style Engine ("千人千面 · 千片千色").
 *
 * - 16 curated luxury editorial star palettes (auto-derived from age, height,
 *   silhouette/cup, career span, or explicitly hand-picked via `profile.style`).
 * - Per-work chromatic mood (`computeTitleMood`) derived from title keywords,
 *   studio/series character, and live cover color sampling so sliding across
 *   works of the same star shifts the entire gallery's atmosphere.
 */

import type { Star, StarProfile, Title } from '~/types/api'

export interface Rgb {
  r: number
  g: number
  b: number
}

export interface PalettePreset {
  id: string
  hue: number
  sat: number
  light: number
  label: string
  mood: string
  swatch: string
}

export interface StarAura {
  /** Selected palette preset id. */
  id: string
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

export interface TitleMood {
  label: string
  rgb: Rgb
  shimmer: Rgb
}

interface RawPalette {
  id: string
  hue: number
  sat: number
  light: number
  label: string
  mood: string
}

const RAW_PALETTES: RawPalette[] = [
  // Desire & Warmth
  { id: 'crimson-velvet', hue: 350, sat: 84, light: 49, label: 'Crimson Velvet', mood: 'Magnetic intensity & unmistakable desire' },
  { id: 'ruby-silk', hue: 358, sat: 82, light: 45, label: 'Ruby Silk', mood: 'Deep scarlet sheen & breathless warmth' },
  { id: 'rosewater-blush', hue: 340, sat: 80, light: 56, label: 'Blush Rose', mood: 'Fresh pulse & luminous skin warmth' },
  { id: 'coral-sunset', hue: 10, sat: 82, light: 53, label: 'Coral Sunset', mood: 'Radiant warmth & sunlit magnetism' },
  { id: 'peach-champagne', hue: 24, sat: 78, light: 50, label: 'Champagne Amber', mood: 'Statuesque golden-hour elegance' },
  { id: 'gilded-honey', hue: 38, sat: 80, light: 46, label: 'Gilded Honey', mood: 'Sunlit nectar & effortless glow' },
  // Nocturnal & Mature
  { id: 'velvet-wine', hue: 326, sat: 68, light: 41, label: 'Velvet Wine', mood: 'Nocturnal depth & seasoned poise' },
  { id: 'obsidian-rose', hue: 334, sat: 54, light: 36, label: 'Obsidian Rose', mood: 'Smoky silk & restrained tension' },
  { id: 'orchid-silk', hue: 294, sat: 66, light: 48, label: 'Orchid Silk', mood: 'Lavender-rose mystique & allure' },
  { id: 'plum-mirage', hue: 268, sat: 66, light: 49, label: 'Plum Mirage', mood: 'Amethyst depth & quiet seduction' },
  { id: 'midnight-indigo', hue: 236, sat: 64, light: 46, label: 'Midnight Indigo', mood: 'Velvet midnight & enigmatic calm' },
  // Crystalline & Editorial
  { id: 'sapphire-dusk', hue: 212, sat: 74, light: 47, label: 'Sapphire Dusk', mood: 'Crystalline poise & cool mystery' },
  { id: 'cerulean-mist', hue: 192, sat: 74, light: 43, label: 'Cerulean Mist', mood: 'Shoreline clarity & airy grace' },
  { id: 'emerald-noir', hue: 162, sat: 72, light: 37, label: 'Emerald Noir', mood: 'Rare jewel-toned sophistication' },
  { id: 'jade-silk', hue: 146, sat: 56, light: 40, label: 'Jade Silk', mood: 'Cool porcelain & serene elegance' },
  { id: 'amber-terracotta', hue: 18, sat: 72, light: 44, label: 'Terracotta Silk', mood: 'Earthy heat & editorial sensuality' },
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

/** All 16 selectable star chromatic presets (used by the interactive Aura Popover). */
export const STAR_PALETTES: PalettePreset[] = RAW_PALETTES.map((p) => {
  const c = hslToRgb(p.hue, p.sat, p.light)
  return {
    ...p,
    swatch: `rgb(${c.r}, ${c.g}, ${c.b})`,
  }
})

const PALETTE_BY_ID = new Map(RAW_PALETTES.map((p) => [p.id, p]))

function parseCupRank(cup?: string | null): number {
  if (!cup) return 0
  const ch = cup.trim().toUpperCase().charCodeAt(0)
  if (ch >= 65 && ch <= 75) return ch - 64
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
 * Compute a star's personal chromatic aura across 16 curated palettes.
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
  const jitter = (seed % 15) - 7

  const explicit = profile.style ? PALETTE_BY_ID.get(profile.style.toLowerCase()) : undefined

  let chosen: RawPalette
  if (explicit) {
    chosen = explicit
  } else if (height !== null && height >= 166) {
    const pool = [RAW_PALETTES[4], RAW_PALETTES[5], RAW_PALETTES[11], RAW_PALETTES[15]]
    chosen = pool[seed % pool.length]
  } else if (cupRank >= 6) {
    const pool = [RAW_PALETTES[0], RAW_PALETTES[1], RAW_PALETTES[3], RAW_PALETTES[15]]
    chosen = pool[seed % pool.length]
  } else if (age !== null && age >= 28) {
    const pool = [RAW_PALETTES[6], RAW_PALETTES[7], RAW_PALETTES[9], RAW_PALETTES[10]]
    chosen = pool[seed % pool.length]
  } else if (age !== null && age <= 23) {
    const pool = [RAW_PALETTES[2], RAW_PALETTES[3], RAW_PALETTES[4], RAW_PALETTES[12]]
    chosen = pool[seed % pool.length]
  } else if (careerYears !== null && careerYears >= 6) {
    const pool = [
      RAW_PALETTES[6], RAW_PALETTES[7], RAW_PALETTES[8], RAW_PALETTES[9],
      RAW_PALETTES[10], RAW_PALETTES[11], RAW_PALETTES[13],
    ]
    chosen = pool[seed % pool.length]
  } else if (careerYears !== null && careerYears <= 2) {
    const pool = [
      RAW_PALETTES[2], RAW_PALETTES[3], RAW_PALETTES[4], RAW_PALETTES[5],
      RAW_PALETTES[12], RAW_PALETTES[14],
    ]
    chosen = pool[seed % pool.length]
  } else {
    chosen = RAW_PALETTES[seed % RAW_PALETTES.length]
  }

  let sat = chosen.sat
  let light = chosen.light
  if (cupRank >= 5) sat = clamp(sat + Math.min(10, (cupRank - 4) * 2), 48, 90)
  if (likedCount > 0) sat = clamp(sat + Math.min(8, likedCount * 2), 48, 92)
  if (height !== null && height >= 164) light = clamp(light + 2, 36, 58)

  const hue = explicit ? chosen.hue : chosen.hue + jitter
  const primary = hslToRgb(hue, sat, light)
  const deep = hslToRgb(hue - 10, clamp(sat - 4, 38, 88), clamp(light - 14, 22, 42))
  const shimmer = hslToRgb(hue + 14, clamp(sat + 6, 55, 96), clamp(light + 22, 66, 82))

  return {
    id: chosen.id,
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

interface TitleMoodRule {
  pattern: RegExp
  label: string
  hue: number
  sat: number
  light: number
}

const TITLE_MOOD_RULES: TitleMoodRule[] = [
  { pattern: /温泉|浴衣|旅館|混浴|湯|湯煙|onsen|yukata/i, label: 'Onsen Steam', hue: 26, sat: 76, light: 50 },
  { pattern: /海|夏|水着|ビキニ|プール|南国|beach|summer|pool|resort/i, label: 'Sunlit Shore', hue: 194, sat: 78, light: 45 },
  { pattern: /夜|ホテル|密室|深夜|不倫|人妻|禁断|NTR|寝取|affair|night|hotel/i, label: 'Nocturnal Velvet', hue: 324, sat: 70, light: 40 },
  { pattern: /OL|オフィス|秘書|スーツ|黒スト|パンスト|上司|残業|office|suit/i, label: 'Glass & Silk', hue: 218, sat: 66, light: 46 },
  { pattern: /純愛|初|デビュー|新人|恋人|甘|イチャ|彼女|debut|first|sweet/i, label: 'Blush Debut', hue: 342, sat: 82, light: 56 },
  { pattern: /痴女|誘惑|濃密|絶頂|痙攣|汗だく|オイル|oil|passion|seduce/i, label: 'Crimson Heat', hue: 354, sat: 86, light: 48 },
  { pattern: /制服|学園|家庭教師|先輩|school|uniform/i, label: 'Porcelain Blue', hue: 204, sat: 70, light: 48 },
  { pattern: /ランジェリー|下着|レース|ドレス|lingerie|lace|silk/i, label: 'Lace Orchid', hue: 292, sat: 68, light: 48 },
  { pattern: /拘束|調教|M男|女王|SM|bondage/i, label: 'Amethyst Tension', hue: 266, sat: 68, light: 46 },
  { pattern: /4K|VR|高画質|BEST|ベスト|完全版/i, label: 'Crystal 4K', hue: 168, sat: 68, light: 40 },
]

/**
 * Derive a distinct chromatic mood for an individual work from its title & code.
 */
export function computeTitleMood(title: Title | null | undefined): TitleMood | null {
  if (!title) return null
  const text = `${title.title ?? ''} ${title.resolution ?? ''}`
  for (const rule of TITLE_MOOD_RULES) {
    if (rule.pattern.test(text)) {
      return {
        label: rule.label,
        rgb: hslToRgb(rule.hue, rule.sat, rule.light),
        shimmer: hslToRgb(rule.hue + 14, clamp(rule.sat + 6, 55, 96), clamp(rule.light + 22, 66, 82)),
      }
    }
  }
  // Fallback: gentle work-specific harmonic from code so every work shifts subtly
  const seed = hashString(title.code)
  const fallbackPalette = RAW_PALETTES[seed % RAW_PALETTES.length]
  return {
    label: fallbackPalette.label,
    rgb: hslToRgb(fallbackPalette.hue, fallbackPalette.sat, fallbackPalette.light),
    shimmer: hslToRgb(fallbackPalette.hue + 14, clamp(fallbackPalette.sat + 6, 55, 96), clamp(fallbackPalette.light + 22, 66, 82)),
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
