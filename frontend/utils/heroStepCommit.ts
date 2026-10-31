/** Pure commit rules for hero horizontal step (testable, no DOM). */

export function swipeCommitDirection(
  dx: number,
  dtMs: number,
  widthPx: number,
): -1 | 1 | null {
  const dt = Math.max(dtMs, 1)
  const vx = dx / dt
  const minDist = Math.min(80, Math.max(44, widthPx * 0.12))
  const flick = Math.abs(vx) >= 0.42 && Math.abs(dx) >= 20
  if (Math.abs(dx) >= minDist || flick) {
    return dx < 0 ? 1 : -1
  }
  return null
}

export function wheelCommitDirection(
  accumulatedDeltaX: number,
  threshold = 72,
): -1 | 1 | null {
  if (Math.abs(accumulatedDeltaX) < threshold) return null
  return accumulatedDeltaX > 0 ? 1 : -1
}

/** True when the event target is the cover — not hero-nav or other chrome. */
export function isHeroCoverGestureTarget(target: EventTarget | null): boolean {
  if (typeof Element === 'undefined' || !(target instanceof Element)) return false
  return !target.closest('button, a, input, textarea, select, label, [data-hero-chrome]')
}
