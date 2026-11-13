import { reactive } from 'vue'

const readyThumbs = reactive(new Set<string>())
const failedThumbs = reactive(new Set<string>())

export function isThumbReady(code: string): boolean {
  return readyThumbs.has(code.toUpperCase())
}

export function markThumbReady(code: string) {
  readyThumbs.add(code.toUpperCase())
}

export function isThumbFailed(code: string): boolean {
  return failedThumbs.has(code.toUpperCase())
}

export function markThumbFailed(code: string) {
  failedThumbs.add(code.toUpperCase())
}

/**
 * Ensures the image is fully decoded before painting.
 * Returns true if the image is valid and decoded; false if decoding failed or image is empty.
 */
export async function decodeThumbImage(img: HTMLImageElement): Promise<boolean> {
  try {
    if (typeof img.decode === 'function') {
      await img.decode()
    }
    return img.naturalWidth > 0 && img.naturalHeight > 0
  } catch {
    return false
  }
}
