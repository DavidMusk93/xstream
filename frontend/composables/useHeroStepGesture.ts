import {
  isHeroCoverGestureTarget,
  swipeCommitDirection,
  wheelCommitDirection,
} from '~/utils/heroStepCommit'

/**
 * Hero cover: at most one title step per input gesture.
 *
 * - Pointer: one commit on release (distance or flick velocity), jitter ignored.
 * - Wheel: accumulate until idle (trackpad momentum), then one commit — same
 *   pattern as debounced horizontal wheel handlers in carousel libraries.
 * - Shared cooldown so wheel + pointer cannot double-fire back-to-back.
 * - Drag follow uses rAF + hero track translate (no per-frame Vue re-render).
 */

const LOCK_SLOP = 12
const WHEEL_IDLE_MS = 220
const GESTURE_COOLDOWN_MS = 650

export function useHeroStepGesture(opts: {
  canStep: () => boolean
  /** Hero stage width for proportional swipe threshold. */
  stageWidth: () => number
  onStep: (delta: -1 | 1) => void
  onShowControls: () => void
  /** Compositor-only horizontal offset during pointer drag (px). */
  setDragTranslate: (px: number) => void
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
  let wheelIdleTimer: ReturnType<typeof setTimeout> | null = null
  let dragRaf = 0
  let pendingDragPx = 0

  function flushDragFrame() {
    dragRaf = 0
    opts.setDragTranslate(pendingDragPx)
  }

  function scheduleDrag(px: number) {
    pendingDragPx = px
    if (dragRaf) return
    dragRaf = requestAnimationFrame(flushDragFrame)
  }

  function clearDragVisual() {
    if (dragRaf) {
      cancelAnimationFrame(dragRaf)
      dragRaf = 0
    }
    pendingDragPx = 0
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

  function stepOnce(delta: -1 | 1) {
    if (!opts.canStep()) return
    const now = Date.now()
    if (now < gestureLockUntil) return
    gestureLockUntil = now + GESTURE_COOLDOWN_MS
    opts.onStep(delta)
    opts.onShowControls()
  }

  function onPointerDown(e: PointerEvent) {
    if (!opts.canStep() || e.button !== 0) return
    if (!isHeroCoverGestureTarget(e.target)) return
    startX = e.clientX
    startY = e.clientY
    startT = performance.now()
    axis = null
    activePointer = e.pointerId
    captureEl = e.currentTarget as HTMLElement
    captureEl.setPointerCapture(e.pointerId)
  }

  function onPointerMove(e: PointerEvent, clampDx: (dx: number) => number) {
    if (activePointer !== e.pointerId) return
    const dx = e.clientX - startX
    const dy = e.clientY - startY
    if (!axis) {
      if (Math.abs(dx) < LOCK_SLOP && Math.abs(dy) < LOCK_SLOP) return
      axis = Math.abs(dx) > Math.abs(dy) * 1.3 ? 'h' : 'v'
      if (axis === 'v') {
        releaseCapture()
        axis = null
        return
      }
      dragging.value = true
    }
    if (axis !== 'h') return
    e.preventDefault()
    scheduleDrag(clampDx(dx))
  }

  function onPointerUp(e: PointerEvent) {
    if (activePointer !== e.pointerId) return
    const dx = e.clientX - startX
    const dt = performance.now() - startT
    const wasHorizontal = axis === 'h'
    resetPointer()
    if (!wasHorizontal) return
    const dir = swipeCommitDirection(dx, dt, opts.stageWidth())
    if (dir == null) return
    stepOnce(dir)
  }

  function onPointerCancel(e: PointerEvent) {
    if (activePointer === e.pointerId) resetPointer()
  }

  function flushWheel() {
    wheelIdleTimer = null
    const dir = wheelCommitDirection(wheelAcc)
    wheelAcc = 0
    if (dir == null) return
    stepOnce(dir)
  }

  function onWheel(e: WheelEvent) {
    if (!opts.canStep()) return
    if (Math.abs(e.deltaX) < Math.abs(e.deltaY) * 0.85) return
    e.preventDefault()

    wheelAcc += e.deltaX
    if (wheelIdleTimer) clearTimeout(wheelIdleTimer)
    wheelIdleTimer = setTimeout(flushWheel, WHEEL_IDLE_MS)
  }

  function onKeydown(e: KeyboardEvent) {
    if (!opts.canStep() || e.repeat) return
    if (e.key === 'ArrowLeft') {
      e.preventDefault()
      stepOnce(-1)
    } else if (e.key === 'ArrowRight') {
      e.preventDefault()
      stepOnce(1)
    }
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
    onKeydown,
  }
}
