import type { Ref } from 'vue'

/**
 * useDismiss — close a popover on outside pointer-down or Escape.
 *
 * Listens only while `open` is true. Pointer-down (not click) so a press on
 * another header trigger closes this panel before that trigger opens its own.
 */
export function useDismiss(root: Ref<HTMLElement | null | undefined>, open: Ref<boolean>) {
  function onPointerDown(e: PointerEvent) {
    const el = root.value
    if (el && !el.contains(e.target as Node)) open.value = false
  }
  function onKeydown(e: KeyboardEvent) {
    if (e.key === 'Escape') open.value = false
  }

  function detach() {
    document.removeEventListener('pointerdown', onPointerDown, true)
    document.removeEventListener('keydown', onKeydown)
  }

  watch(open, (isOpen) => {
    if (typeof document === 'undefined') return
    if (isOpen) {
      document.addEventListener('pointerdown', onPointerDown, true)
      document.addEventListener('keydown', onKeydown)
    } else {
      detach()
    }
  })

  onUnmounted(detach)
}
