import {
  isHeroCoverGestureTarget,
  isNewWheelGesture,
  swipeCommitDirection,
  wheelCommitDirection,
} from '~/utils/heroStepCommit'

/**
 * Hero cover: at most one title step per input gesture.
 *
 * - Pointer (mouse & touch): direct 1:1 tracking, rubber-band resistance at bounds,
 *   critically damped glide on release, strictly 1 slide per swipe/flick.
 * - Trackpad / Wheel (incl. Shift+Wheel for mice): live damped visual peek while
 *   accumulating, instantaneous single-step commit, then inertia-aware lockout so
 *   macOS/Windows momentum tails never double-step.
 */

const LOCK_SLOP = 8
const WHEEL_IDLE_MS = 260
const GESTURE_COOLDOWN_MS = 260
const WHEEL_PEEK_FACTOR = 0.42
const WHEEL_PEEK_MAX_PX = 88

export function useHeroStepGesture(opts: {
  canStep: () => boolean
  canDrag?: () => boolean
  /** Hero stage width for proportional swipe threshold. */
  stageWidth: () => number
  /** Clamp / rubber-band horizontal drag offset (px). */
  clampDx?: (dx: number) => number
  onStep: (delta: number) => void
  onShowControls: () => void
  /** Compositor-only horizontal offset during pointer drag or wheel peek (px). */
  setDragTranslate: (px: number) => void
  /** Once per rAF while locked horizontal — prefetch / widen slide window. */
  onHorizontalDrag?: (rawDx: number, clampedDx: number) => void
  /** Trackpad wheel accumulating — warm the likely next slide. */
  onWheelAccumulate?: (accumulatedDeltaX: number) => void
  /** Release handler for smooth momentum settle. */
  onDragRelease?: (info: {
    dx: number
    clampedDx: number
    dt: number
    dir: -1 | 1 | null
    done: () => void
  }) => void
}) {
  const dragging = ref(false)

  let startX = 0
  let startY = 0
  let startT = 0
  let axis: 'h' | 'v' | null = null
  let activePointer: number | null = null
  let captureEl: HTMLElement | null = null
  let gestureLockUntil = 0

  let wheelAcc = 0
  let wheelLocked = false
  let wheelPeeking = false
  let wheelCommitDir: -1 | 1 | 0 = 0
  let wheelCommitAt = 0
  let wheelPrevAbsDelta = 0
  let wheelIdleTimer: ReturnType<typeof setTimeout> | null = null

  let dragRaf = 0
  let pendingDragPx = 0
  let pendingDragRaw = 0

  function flushDragFrame() {
    dragRaf = 0
    opts.onHorizontalDrag?.(pendingDragRaw, pendingDragPx)
  }

  function scheduleDrag(rawDx: number, clampedDx: number) {
    pendingDragRaw = rawDx
    pendingDragPx = clampedDx
    opts.setDragTranslate(clampedDx)
    if (!dragRaf) {
      dragRaf = requestAnimationFrame(flushDragFrame)
    }
  }

  function clearDragVisual() {
    if (dragRaf) {
      cancelAnimationFrame(dragRaf)
      dragRaf = 0
    }
    pendingDragPx = 0
    pendingDragRaw = 0
    opts.setDragTranslate(0)
  }

  function releaseCapture() {
    if (captureEl != null && activePointer != null) {
      try {
        captureEl.releasePointerCapture(activePointer)
      } catch {
        // Already released.
      }
    }
    captureEl = null
    activePointer = null
  }

  function stepOnce(delta: -1 | 1) {
    if (!opts.canStep()) return
    const now = Date.now()
    if (now < gestureLockUntil) return
    gestureLockUntil = now + GESTURE_COOLDOWN_MS
    opts.onStep(delta)
    opts.onShowControls()
  }

  function onPointerDown(e: PointerEvent) {
    const can = opts.canDrag ? opts.canDrag() : opts.canStep()
    if (!can || e.button !== 0) return
    if (!isHeroCoverGestureTarget(e.target)) return
    if (activePointer != null) return

    if (wheelPeeking) {
      wheelPeeking = false
      wheelAcc = 0
      opts.setDragTranslate(0)
    }

    startX = e.clientX
    startY = e.clientY
    startT = performance.now()
    axis = null
    pendingDragPx = 0
    pendingDragRaw = 0
    activePointer = e.pointerId
    captureEl = e.currentTarget as HTMLElement
    // On mouse, capture pointer so drag continues smoothly outside the stage.
    // On touch, native routing already keeps delivery to the initial target.
    if (e.pointerType === 'mouse') {
      try {
        captureEl.setPointerCapture(e.pointerId)
      } catch {
        // Ignore if capture fails
      }
    }
  }

  function onPointerMove(e: PointerEvent, clampDx: (dx: number) => number) {
    if (activePointer !== e.pointerId) return
    const dx = e.clientX - startX
    const dy = e.clientY - startY
    if (!axis) {
      if (Math.abs(dx) < LOCK_SLOP && Math.abs(dy) < LOCK_SLOP) return
      // 0.75 ratio (~53 deg) accommodates natural thumb sweep arcs on mobile
      if (Math.abs(dx) >= Math.abs(dy) * 0.75) {
        axis = 'h'
        dragging.value = true
      } else {
        axis = 'v'
        releaseCapture()
        return
      }
    }
    if (axis !== 'h') return
    e.preventDefault()
    scheduleDrag(dx, clampDx(dx))
  }

  function onPointerUp(e: PointerEvent) {
    if (activePointer !== e.pointerId) return
    const dx = e.clientX - startX
    const dt = performance.now() - startT
    const wasHorizontal = axis === 'h'
    const finalClampedPx = pendingDragPx

    if (dragRaf) {
      cancelAnimationFrame(dragRaf)
      dragRaf = 0
    }
    releaseCapture()
    axis = null
    activePointer = null

    if (!wasHorizontal) {
      dragging.value = false
      clearDragVisual()
      return
    }

    const dir = finalClampedPx === 0 ? null : swipeCommitDirection(dx, dt, opts.stageWidth())
    if (opts.onDragRelease) {
      opts.onDragRelease({
        dx,
        clampedDx: finalClampedPx,
        dt,
        dir,
        done: () => {
          dragging.value = false
          clearDragVisual()
        },
      })
    } else {
      dragging.value = false
      clearDragVisual()
      if (dir != null) {
        stepOnce(dir)
      }
    }
  }

  function onPointerCancel(e: PointerEvent) {
    if (activePointer !== e.pointerId) return
    const dx = pendingDragRaw
    const dt = Math.max(1, performance.now() - startT)
    const finalClampedPx = pendingDragPx
    const wasHorizontal = axis === 'h'

    if (dragRaf) {
      cancelAnimationFrame(dragRaf)
      dragRaf = 0
    }
    releaseCapture()
    axis = null
    activePointer = null

    if (wasHorizontal && opts.onDragRelease) {
      const dir = finalClampedPx === 0 ? null : swipeCommitDirection(dx, dt, opts.stageWidth())
      opts.onDragRelease({
        dx,
        clampedDx: finalClampedPx,
        dt,
        dir,
        done: () => {
          dragging.value = false
          clearDragVisual()
        },
      })
    } else {
      dragging.value = false
      clearDragVisual()
    }
  }

  function resetWheelIdle() {
    wheelLocked = false
    wheelAcc = 0
    wheelCommitDir = 0
    wheelPrevAbsDelta = 0
    if (wheelPeeking) {
      wheelPeeking = false
      dragging.value = false
      opts.setDragTranslate(0)
    }
  }

  function scheduleWheelIdle() {
    if (wheelIdleTimer) clearTimeout(wheelIdleTimer)
    wheelIdleTimer = setTimeout(resetWheelIdle, WHEEL_IDLE_MS)
  }

  function onWheel(e: WheelEvent) {
    if (!(opts.canDrag ? opts.canDrag() : opts.canStep())) return

    // Support both horizontal trackpad gestures and Shift+Wheel on traditional mice.
    const rawDelta =
      e.shiftKey && Math.abs(e.deltaX) < Math.abs(e.deltaY) ? e.deltaY : e.deltaX
    const orthoDelta =
      e.shiftKey && Math.abs(e.deltaX) < Math.abs(e.deltaY) ? e.deltaX : e.deltaY

    if (Math.abs(rawDelta) < 0.5 || Math.abs(rawDelta) < Math.abs(orthoDelta) * 0.9) return
    e.preventDefault()

    // Normalize line/page wheel modes (traditional mouse wheels) to pixel-like units.
    const delta =
      e.deltaMode === 1 ? rawDelta * 28 : e.deltaMode === 2 ? rawDelta * 120 : rawDelta
    const absDelta = Math.abs(delta)
    const now = performance.now()

    if (wheelLocked) {
      const sameDir =
        wheelCommitDir !== 0 && Math.sign(delta) === Math.sign(wheelCommitDir)
      const sinceCommit = now - wheelCommitAt
      const isNew = isNewWheelGesture(absDelta, wheelPrevAbsDelta, sameDir, sinceCommit)
      wheelPrevAbsDelta = absDelta
      if (!isNew) {
        // Still absorbing momentum inertia tail from the previous swipe.
        scheduleWheelIdle()
        return
      }
      // Clear new intentional gesture detected — unlock immediately.
      wheelLocked = false
      wheelAcc = 0
      wheelCommitDir = 0
    }

    wheelPrevAbsDelta = absDelta
    wheelAcc += delta
    opts.onWheelAccumulate?.(wheelAcc)

    const dir = wheelCommitDirection(wheelAcc)
    if (dir != null) {
      wheelLocked = true
      wheelCommitDir = dir
      wheelCommitAt = now
      wheelAcc = 0
      if (wheelPeeking) {
        wheelPeeking = false
        dragging.value = false
      }
      opts.setDragTranslate(0)
      stepOnce(dir)
    } else {
      // Live damped peek while accumulating so trackpad feels immediately responsive.
      const rawPeek = Math.max(
        -WHEEL_PEEK_MAX_PX,
        Math.min(WHEEL_PEEK_MAX_PX, -wheelAcc * WHEEL_PEEK_FACTOR),
      )
      const clampedPeek = opts.clampDx ? opts.clampDx(rawPeek) : rawPeek
      wheelPeeking = true
      dragging.value = true
      opts.setDragTranslate(clampedPeek)
    }

    scheduleWheelIdle()
  }

  onUnmounted(() => {
    if (wheelIdleTimer) clearTimeout(wheelIdleTimer)
    if (dragRaf) cancelAnimationFrame(dragRaf)
    clearDragVisual()
  })

  return {
    dragging,
    onPointerDown,
    onPointerMove,
    onPointerUp,
    onPointerCancel,
    onWheel,
  }
}
