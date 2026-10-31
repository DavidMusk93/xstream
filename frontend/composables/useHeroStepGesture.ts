import { swipeCommitDirection, wheelCommitDirection } from '~/utils/heroStepCommit'

/**
 * Hero cover: at most one title step per input gesture.
 *
 * - Pointer: one commit on release (distance or flick velocity), jitter ignored.
 * - Wheel: accumulate until idle (trackpad momentum), then one commit — same
 *   pattern as debounced horizontal wheel handlers in carousel libraries.
 * - Shared cooldown so wheel + pointer cannot double-fire back-to-back.
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
}) {
  const dragX = ref(0)
  const dragging = ref(false)

  let startX = 0
  let startT = 0
  let axis: 'h' | 'v' | null = null
  let activePointer: number | null = null
  let gestureLockUntil = 0
  let wheelAcc = 0
  let wheelIdleTimer: ReturnType<typeof setTimeout> | null = null

  function resetPointer() {
    dragging.value = false
    axis = null
    activePointer = null
    dragX.value = 0
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
    startX = e.clientX
    startT = performance.now()
    axis = null
    dragging.value = true
    activePointer = e.pointerId
    ;(e.currentTarget as HTMLElement).setPointerCapture(e.pointerId)
  }

  function onPointerMove(e: PointerEvent, clampDx: (dx: number) => number) {
    if (!dragging.value || activePointer !== e.pointerId) return
    const dx = e.clientX - startX
    const dy = e.clientY - startY
    if (!axis) {
      if (Math.abs(dx) < LOCK_SLOP && Math.abs(dy) < LOCK_SLOP) return
      axis = Math.abs(dx) > Math.abs(dy) * 1.3 ? 'h' : 'v'
      if (axis === 'v') {
        resetPointer()
        return
      }
    }
    if (axis !== 'h') return
    e.preventDefault()
    dragX.value = clampDx(dx)
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
  })

  return {
    dragX,
    dragging,
    onPointerDown,
    onPointerMove,
    onPointerUp,
    onPointerCancel,
    onWheel,
    onKeydown,
  }
}
