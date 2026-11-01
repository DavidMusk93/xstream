import {
  isHeroCoverGestureTarget,
  swipeCommitDirection,
  wheelCommitDirection,
} from '~/utils/heroStepCommit'

/**
 * Hero cover: at most one title step per input gesture.
 *
 * - Pointer: direct 1:1 finger tracking, rubberband resistance at bounds,
 *   smooth spring settle on release with zero teleport/jitter.
 * - Wheel: instantaneous commit once threshold is crossed, then momentum
 *   cooldown until idle.
 * - Interruptible: touching down during transition catches the stage cleanly.
 */

const LOCK_SLOP = 8
const WHEEL_IDLE_MS = 180
const GESTURE_COOLDOWN_MS = 280

export function useHeroStepGesture(opts: {
  canStep: () => boolean
  canDrag?: () => boolean
  /** Hero stage width for proportional swipe threshold. */
  stageWidth: () => number
  onStep: (delta: number) => void
  onShowControls: () => void
  /** Compositor-only horizontal offset during pointer drag (px). */
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
    dir: number | null
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

  function resetPointer() {
    dragging.value = false
    axis = null
    releaseCapture()
    clearDragVisual()
  }

  function stepOnce(delta: number) {
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

    startX = e.clientX
    startY = e.clientY
    startT = performance.now()
    axis = null
    pendingDragPx = 0
    pendingDragRaw = 0
    activePointer = e.pointerId
    captureEl = e.currentTarget as HTMLElement
    // On mouse, capture pointer so drag continues outside window.
    // On touch, native touch routing already keeps delivery to initial target,
    // while setPointerCapture on iOS Safari can trigger gesture cancellation.
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
      // Use 0.75 ratio (~53 degrees) to accommodate natural thumb sweep arcs on mobile
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
      // Evaluate commit based on distance already traveled before cancel, instead of blindly discarding
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

  function onWheel(e: WheelEvent) {
    if (!opts.canStep()) return
    if (Math.abs(e.deltaX) < Math.abs(e.deltaY) * 0.85) return
    e.preventDefault()

    if (wheelLocked) {
      if (wheelIdleTimer) clearTimeout(wheelIdleTimer)
      wheelIdleTimer = setTimeout(() => {
        wheelLocked = false
        wheelAcc = 0
      }, WHEEL_IDLE_MS)
      return
    }

    wheelAcc += e.deltaX
    opts.onWheelAccumulate?.(wheelAcc)

    const dir = wheelCommitDirection(wheelAcc)
    if (dir != null) {
      wheelLocked = true
      wheelAcc = 0
      stepOnce(dir)
    }

    if (wheelIdleTimer) clearTimeout(wheelIdleTimer)
    wheelIdleTimer = setTimeout(() => {
      wheelLocked = false
      wheelAcc = 0
    }, WHEEL_IDLE_MS)
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
