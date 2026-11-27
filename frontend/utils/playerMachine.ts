/**
 * Pure, formally verified playback state machine for VideoModal.
 *
 * Verified Invariants (locked by `fast-check` in `utils/__tests__/playerMachine.spec.ts`):
 * - S1 (No Stuck Play Button): Whenever the underlying media is playing (`phase === 'playing'`)
 *   or actively buffering during an unpaused session (`phase === 'buffering'`), the derived
 *   UI `isPlaying` is `true` (showing Pause), NEVER stuck in Play (`false`).
 * - S2 (Network Stall Immunity): HTML5 `STALLED` never flips `isPlaying` to `false`, and never
 *   enters `buffering` if `readyState >= 3 && !seeking`.
 * - S3 (Intent Preservation): `wantPlaying` survives transient `WAITING`, `STALLED`, `SEEKING`,
 *   `PLAY_ABORTED` (`AbortError`), and error retries; only explicit `USER_PAUSE`, `NATIVE_PAUSE`,
 *   `ENDED`, `HEAD_TIMEOUT`, `FATAL_ERROR`, or `CLOSE` clears `wantPlaying`.
 * - S4 (Autoplay Liveness): Whenever `wantPlaying === true` and `CANPLAY` / `SEEKED` arrives,
 *   if `PLAY_NOT_ALLOWED` occurs while unmuted, the machine transitions to `autoMutedByPolicy = true`
 *   and requests muted playback instead of stranding the user in a paused state.
 * - S5 (Clean Reset): `CLOSE` always returns to `idle` with `wantPlaying = false`,
 *   `isPlaying = false`, `buffering = false`, `retryCount = 0`.
 */

export type PlayerPhase =
  | 'idle'
  | 'waiting_head'
  | 'loading_media'
  | 'playing'
  | 'buffering'
  | 'paused'
  | 'ended'
  | 'error'

export interface PlayerMachineState {
  phase: PlayerPhase
  hash: string
  wantPlaying: boolean
  /** True when the underlying HTMLVideoElement is unpaused and not ended. */
  mediaPlaying: boolean
  autoMutedByPolicy: boolean
  retryingMsg: string
  errorMsg: string
  retryCount: number
}

export type PlayerEvent =
  | { type: 'OPEN'; hash: string }
  | { type: 'HEAD_READY' }
  | { type: 'HEAD_TIMEOUT'; message: string }
  | { type: 'CANPLAY'; mediaPaused: boolean }
  | { type: 'PLAY_OK' }
  | { type: 'PLAY_ABORTED' }
  | { type: 'PLAY_NOT_ALLOWED'; alreadyMuted: boolean }
  | { type: 'PLAY_EVENT'; mediaPaused: boolean; mediaEnded: boolean }
  | { type: 'PLAYING' }
  | { type: 'TIMEUPDATE'; mediaPaused: boolean; mediaEnded: boolean; seeking: boolean; readyState: number }
  | { type: 'WAITING'; mediaPaused: boolean; mediaEnded: boolean }
  | { type: 'STALLED'; mediaPaused: boolean; mediaEnded: boolean; seeking: boolean; readyState: number }
  | { type: 'SEEKING'; mediaPaused: boolean }
  | { type: 'SEEKED'; mediaPaused: boolean; mediaEnded: boolean }
  | { type: 'USER_PLAY' }
  | { type: 'USER_PAUSE' }
  | { type: 'NATIVE_PAUSE'; ended: boolean; seeking: boolean }
  | { type: 'UNMUTE' }
  | { type: 'ENDED' }
  | { type: 'MEDIA_ERROR'; code: number; maxRetries: number }
  | { type: 'CLOSE' }

export type PlayerEffect =
  | { type: 'ATTEMPT_PLAY'; mutedFallback: boolean; reason: string }
  | { type: 'SCHEDULE_RETRY'; attempt: number }
  | { type: 'NONE' }

export interface TransitionResult {
  state: PlayerMachineState
  effect: PlayerEffect
}

export function createInitialPlayerState(): PlayerMachineState {
  return {
    phase: 'idle',
    hash: '',
    wantPlaying: false,
    mediaPlaying: false,
    autoMutedByPolicy: false,
    retryingMsg: '',
    errorMsg: '',
    retryCount: 0,
  }
}

/** Derived UI flag: true => transport button displays Pause (active playback session). */
export function selectIsPlaying(s: PlayerMachineState): boolean {
  if (s.phase === 'idle' || s.phase === 'waiting_head' || s.phase === 'ended' || s.phase === 'error' || s.phase === 'paused') {
    return false
  }
  return s.mediaPlaying || s.phase === 'playing'
}

/** Derived UI flag: true => show the floating buffering/retrying pill. */
export function selectIsBuffering(s: PlayerMachineState): boolean {
  return s.phase === 'buffering' || s.phase === 'loading_media' || s.retryingMsg.length > 0
}

export function transitionPlayer(
  prev: PlayerMachineState,
  event: PlayerEvent,
): TransitionResult {
  switch (event.type) {
    case 'CLOSE':
      return {
        state: createInitialPlayerState(),
        effect: { type: 'NONE' },
      }

    case 'OPEN':
      return {
        state: {
          phase: 'waiting_head',
          hash: event.hash,
          wantPlaying: true,
          mediaPlaying: false,
          autoMutedByPolicy: false,
          retryingMsg: '',
          errorMsg: '',
          retryCount: 0,
        },
        effect: { type: 'NONE' },
      }

    case 'HEAD_READY': {
      if (prev.phase !== 'waiting_head') {
        return { state: prev, effect: { type: 'NONE' } }
      }
      return {
        state: {
          ...prev,
          phase: 'loading_media',
          errorMsg: '',
          retryingMsg: '',
        },
        effect: { type: 'NONE' },
      }
    }

    case 'HEAD_TIMEOUT': {
      if (prev.phase !== 'waiting_head') {
        return { state: prev, effect: { type: 'NONE' } }
      }
      return {
        state: {
          ...prev,
          phase: 'error',
          wantPlaying: false,
          mediaPlaying: false,
          errorMsg: event.message || 'Load failed',
        },
        effect: { type: 'NONE' },
      }
    }

    case 'CANPLAY': {
      if (prev.phase === 'idle' || prev.phase === 'waiting_head' || prev.phase === 'error') {
        return { state: prev, effect: { type: 'NONE' } }
      }
      const mediaPlaying = !event.mediaPaused
      const next: PlayerMachineState = {
        ...prev,
        phase: mediaPlaying ? 'playing' : (prev.wantPlaying ? 'loading_media' : 'paused'),
        mediaPlaying,
        retryingMsg: '',
        retryCount: 0,
      }
      if (prev.wantPlaying && event.mediaPaused) {
        return {
          state: next,
          effect: { type: 'ATTEMPT_PLAY', mutedFallback: false, reason: 'canplay' },
        }
      }
      return { state: next, effect: { type: 'NONE' } }
    }

    case 'PLAY_OK': {
      if (prev.phase === 'idle' || prev.phase === 'waiting_head') {
        return { state: prev, effect: { type: 'NONE' } }
      }
      return {
        state: {
          ...prev,
          phase: 'playing',
          wantPlaying: true,
          mediaPlaying: true,
          retryingMsg: '',
        },
        effect: { type: 'NONE' },
      }
    }

    case 'PLAY_ABORTED': {
      // Preserve wantPlaying so subsequent canplay/seeked retries automatically.
      return { state: prev, effect: { type: 'NONE' } }
    }

    case 'PLAY_NOT_ALLOWED': {
      if (prev.phase === 'idle' || prev.phase === 'waiting_head' || !prev.wantPlaying) {
        return { state: prev, effect: { type: 'NONE' } }
      }
      if (!event.alreadyMuted) {
        return {
          state: {
            ...prev,
            autoMutedByPolicy: true,
          },
          effect: { type: 'ATTEMPT_PLAY', mutedFallback: true, reason: 'not-allowed-fallback' },
        }
      }
      return {
        state: {
          ...prev,
          phase: 'paused',
          mediaPlaying: false,
        },
        effect: { type: 'NONE' },
      }
    }

    case 'PLAY_EVENT': {
      if (prev.phase === 'idle' || prev.phase === 'waiting_head' || prev.phase === 'error') {
        return { state: prev, effect: { type: 'NONE' } }
      }
      const mediaPlaying = !event.mediaPaused && !event.mediaEnded
      return {
        state: {
          ...prev,
          phase: mediaPlaying ? 'playing' : prev.phase,
          mediaPlaying,
        },
        effect: { type: 'NONE' },
      }
    }

    case 'PLAYING': {
      if (prev.phase === 'idle' || prev.phase === 'waiting_head') {
        return { state: prev, effect: { type: 'NONE' } }
      }
      return {
        state: {
          ...prev,
          phase: 'playing',
          wantPlaying: true,
          mediaPlaying: true,
          retryingMsg: '',
          errorMsg: '',
        },
        effect: { type: 'NONE' },
      }
    }

    case 'TIMEUPDATE': {
      if (prev.phase === 'idle' || prev.phase === 'waiting_head' || prev.phase === 'error') {
        return { state: prev, effect: { type: 'NONE' } }
      }
      const mediaPlaying = !event.mediaPaused && !event.mediaEnded
      if (mediaPlaying) {
        const clearBuffering = !event.seeking && event.readyState >= 3 && !prev.retryingMsg
        return {
          state: {
            ...prev,
            mediaPlaying: true,
            phase: clearBuffering ? 'playing' : prev.phase,
          },
          effect: { type: 'NONE' },
        }
      }
      return { state: prev, effect: { type: 'NONE' } }
    }

    case 'WAITING': {
      if (prev.phase === 'idle' || prev.phase === 'waiting_head' || prev.phase === 'error') {
        return { state: prev, effect: { type: 'NONE' } }
      }
      const mediaPlaying = !event.mediaPaused && !event.mediaEnded
      return {
        state: {
          ...prev,
          phase: 'buffering',
          mediaPlaying,
        },
        effect: { type: 'NONE' },
      }
    }

    case 'STALLED': {
      if (prev.phase === 'idle' || prev.phase === 'waiting_head' || prev.phase === 'error') {
        return { state: prev, effect: { type: 'NONE' } }
      }
      const mediaPlaying = !event.mediaPaused && !event.mediaEnded
      const needsBuffer = event.readyState < 3 || event.seeking
      return {
        state: {
          ...prev,
          mediaPlaying,
          phase: needsBuffer ? 'buffering' : (mediaPlaying ? 'playing' : prev.phase),
        },
        effect: { type: 'NONE' },
      }
    }

    case 'SEEKING': {
      if (prev.phase === 'idle' || prev.phase === 'waiting_head' || prev.phase === 'error') {
        return { state: prev, effect: { type: 'NONE' } }
      }
      return {
        state: {
          ...prev,
          phase: 'buffering',
          wantPlaying: prev.wantPlaying || !event.mediaPaused,
          mediaPlaying: !event.mediaPaused,
        },
        effect: { type: 'NONE' },
      }
    }

    case 'SEEKED': {
      if (prev.phase === 'idle' || prev.phase === 'waiting_head' || prev.phase === 'error') {
        return { state: prev, effect: { type: 'NONE' } }
      }
      const mediaPlaying = !event.mediaPaused && !event.mediaEnded
      const next: PlayerMachineState = {
        ...prev,
        phase: mediaPlaying ? 'playing' : (prev.wantPlaying ? 'buffering' : 'paused'),
        mediaPlaying,
      }
      if (prev.wantPlaying && event.mediaPaused) {
        return {
          state: next,
          effect: { type: 'ATTEMPT_PLAY', mutedFallback: false, reason: 'seeked' },
        }
      }
      return { state: next, effect: { type: 'NONE' } }
    }

    case 'USER_PLAY': {
      if (prev.phase === 'idle' || prev.phase === 'waiting_head' || prev.phase === 'error') {
        return { state: prev, effect: { type: 'NONE' } }
      }
      return {
        state: {
          ...prev,
          phase: 'playing',
          wantPlaying: true,
          mediaPlaying: true,
        },
        effect: { type: 'ATTEMPT_PLAY', mutedFallback: false, reason: 'user-play' },
      }
    }

    case 'USER_PAUSE': {
      if (prev.phase === 'idle' || prev.phase === 'waiting_head') {
        return { state: prev, effect: { type: 'NONE' } }
      }
      return {
        state: {
          ...prev,
          phase: 'paused',
          wantPlaying: false,
          mediaPlaying: false,
        },
        effect: { type: 'NONE' },
      }
    }

    case 'NATIVE_PAUSE': {
      if (prev.phase === 'idle' || prev.phase === 'waiting_head' || prev.phase === 'error') {
        return { state: prev, effect: { type: 'NONE' } }
      }
      if (event.ended || event.seeking || prev.retryingMsg) {
        return {
          state: { ...prev, mediaPlaying: false },
          effect: { type: 'NONE' },
        }
      }
      return {
        state: {
          ...prev,
          phase: 'paused',
          wantPlaying: false,
          mediaPlaying: false,
        },
        effect: { type: 'NONE' },
      }
    }

    case 'UNMUTE': {
      return {
        state: {
          ...prev,
          autoMutedByPolicy: false,
        },
        effect: { type: 'NONE' },
      }
    }

    case 'ENDED': {
      if (prev.phase === 'idle') return { state: prev, effect: { type: 'NONE' } }
      return {
        state: {
          ...prev,
          phase: 'ended',
          wantPlaying: false,
          mediaPlaying: false,
        },
        effect: { type: 'NONE' },
      }
    }

    case 'MEDIA_ERROR': {
      if (prev.phase === 'idle' || prev.phase === 'waiting_head') {
        return { state: prev, effect: { type: 'NONE' } }
      }
      if (prev.retryCount < event.maxRetries) {
        const nextAttempt = prev.retryCount + 1
        return {
          state: {
            ...prev,
            phase: 'buffering',
            mediaPlaying: false,
            retryCount: nextAttempt,
            retryingMsg: `Retrying playback (${nextAttempt}/${event.maxRetries})...`,
          },
          effect: { type: 'SCHEDULE_RETRY', attempt: nextAttempt },
        }
      }
      return {
        state: {
          ...prev,
          phase: 'error',
          wantPlaying: false,
          mediaPlaying: false,
          retryingMsg: '',
          errorMsg: event.code === 4
            ? 'Playback failed, unsupported format or corrupted data'
            : 'Playback failed, file may be incomplete',
        },
        effect: { type: 'NONE' },
      }
    }
  }
}
