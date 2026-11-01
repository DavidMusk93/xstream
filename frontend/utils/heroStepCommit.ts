/** Pure commit rules for hero horizontal step (testable, no DOM). */

export function swipeCommitDirection(
  dx: number,
  dtMs: number,
  widthPx: number,
): number | null {
  const dt = Math.max(dtMs, 1)
  const vx = dx / dt
  const w = Math.max(widthPx, 200)
  const minDist = Math.min(48, Math.max(28, w * 0.08))
  const flick = Math.abs(vx) >= 0.28 && Math.abs(dx) >= 20

  if (Math.abs(dx) < minDist && !flick) {
    return null
  }

  // Momentum projection: project how far the swipe naturally travels (120ms of inertia)
  const projectedDx = dx + vx * 120
  const rawSteps = -projectedDx / w
  let steps = Math.sign(rawSteps) * Math.round(Math.abs(rawSteps))

  // Ensure at least 1 step in the drag direction if threshold was met
  const dir = dx < 0 ? 1 : -1
  if (dir > 0) {
    steps = Math.max(1, steps)
  } else {
    steps = Math.min(-1, steps)
  }

  // Cap max multi-step swipe to 4 slides at once
  return Math.min(4, Math.max(-4, steps))
}

export function wheelCommitDirection(
  accumulatedDeltaX: number,
  threshold = 72,
): -1 | 1 | null {
  if (Math.abs(accumulatedDeltaX) < threshold) return null
  return accumulatedDeltaX > 0 ? 1 : -1
}

/** True when the event target is the cover or hero-nav — not other interactive chrome. */
export function isHeroCoverGestureTarget(target: EventTarget | null): boolean {
  if (typeof Element === 'undefined' || !(target instanceof Element)) return false
  if (target.closest('[data-hero-nav]')) return true
  return !target.closest('button, a, input, textarea, select, label, [data-hero-chrome]')
}
