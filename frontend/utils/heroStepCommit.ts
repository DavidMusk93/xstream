/** Pure commit & resistance rules for hero horizontal step (testable, no DOM). */

/**
 * Strictly returns `-1 | 1 | null` — at most ONE slide per pointer swipe/flick.
 * Fast or long drags never skip multiple covers.
 */
export function swipeCommitDirection(
  dx: number,
  dtMs: number,
  widthPx: number,
): -1 | 1 | null {
  const dt = Math.max(dtMs, 1)
  const vx = dx / dt
  const w = Math.max(widthPx, 200)
  const minDist = Math.min(56, Math.max(32, w * 0.1))
  const flick = Math.abs(vx) >= 0.28 && Math.abs(dx) >= 20

  if (Math.abs(dx) < minDist && !flick) {
    return null
  }
  return dx < 0 ? 1 : -1
}

export function wheelCommitDirection(
  accumulatedDeltaX: number,
  threshold = 64,
): -1 | 1 | null {
  if (Math.abs(accumulatedDeltaX) < threshold) return null
  return accumulatedDeltaX > 0 ? 1 : -1
}

/**
 * Apple-style rubber-band resistance at the first/last slide; 1:1 inside bounds.
 */
export function rubberBandDrag(
  dx: number,
  atStart: boolean,
  atEnd: boolean,
): number {
  if ((atStart && dx > 0) || (atEnd && dx < 0)) {
    return (dx * 0.24) / (1 + Math.abs(dx) / 220)
  }
  return dx
}

/**
 * Distinguish a genuine new trackpad gesture from macOS/Windows momentum inertia tail.
 *
 * - Direction reversal after 160ms with deliberate movement (>= 8px) unlocks immediately.
 * - Same-direction re-acceleration spike after 320ms unlocks for a second deliberate swipe.
 * - Decaying inertia events stay locked so one swipe never moves multiple covers.
 */
export function isNewWheelGesture(
  absDelta: number,
  prevAbsDelta: number,
  sameDir: boolean,
  sinceCommitMs: number,
): boolean {
  if (!sameDir) {
    return sinceCommitMs >= 160 && absDelta >= 8
  }
  return sinceCommitMs >= 320 && absDelta > prevAbsDelta * 2.2 + 12
}

/** True when the event target is the cover or hero-nav — not other interactive chrome. */
export function isHeroCoverGestureTarget(target: EventTarget | null): boolean {
  if (typeof Element === 'undefined' || !(target instanceof Element)) return false
  if (target.closest('[data-hero-nav]')) return true
  return !target.closest('button, a, input, textarea, select, label, [data-hero-chrome]')
}
