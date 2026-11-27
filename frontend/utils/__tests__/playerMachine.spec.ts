import { describe, it, expect } from 'vitest'
import fc from 'fast-check'
import {
  createInitialPlayerState,
  selectIsBuffering,
  selectIsPlaying,
  transitionPlayer,
  type PlayerEvent,
  type PlayerMachineState,
} from '../playerMachine'

const arbEvent: fc.Arbitrary<PlayerEvent> = fc.oneof(
  fc.constant<PlayerEvent>({ type: 'OPEN', hash: 'a'.repeat(40) }),
  fc.constant<PlayerEvent>({ type: 'HEAD_READY' }),
  fc.constant<PlayerEvent>({ type: 'HEAD_TIMEOUT', message: 'Load timeout' }),
  fc.boolean().map<PlayerEvent>(mediaPaused => ({ type: 'CANPLAY', mediaPaused })),
  fc.constant<PlayerEvent>({ type: 'PLAY_OK' }),
  fc.constant<PlayerEvent>({ type: 'PLAY_ABORTED' }),
  fc.boolean().map<PlayerEvent>(alreadyMuted => ({ type: 'PLAY_NOT_ALLOWED', alreadyMuted })),
  fc.record({ mediaPaused: fc.boolean(), mediaEnded: fc.boolean() }).map<PlayerEvent>(r => ({ type: 'PLAY_EVENT', ...r })),
  fc.constant<PlayerEvent>({ type: 'PLAYING' }),
  fc.record({
    mediaPaused: fc.boolean(),
    mediaEnded: fc.boolean(),
    seeking: fc.boolean(),
    readyState: fc.integer({ min: 0, max: 4 }),
  }).map<PlayerEvent>(r => ({ type: 'TIMEUPDATE', ...r })),
  fc.record({ mediaPaused: fc.boolean(), mediaEnded: fc.boolean() }).map<PlayerEvent>(r => ({ type: 'WAITING', ...r })),
  fc.record({
    mediaPaused: fc.boolean(),
    mediaEnded: fc.boolean(),
    seeking: fc.boolean(),
    readyState: fc.integer({ min: 0, max: 4 }),
  }).map<PlayerEvent>(r => ({ type: 'STALLED', ...r })),
  fc.boolean().map<PlayerEvent>(mediaPaused => ({ type: 'SEEKING', mediaPaused })),
  fc.record({ mediaPaused: fc.boolean(), mediaEnded: fc.boolean() }).map<PlayerEvent>(r => ({ type: 'SEEKED', ...r })),
  fc.constant<PlayerEvent>({ type: 'USER_PLAY' }),
  fc.constant<PlayerEvent>({ type: 'USER_PAUSE' }),
  fc.record({ ended: fc.boolean(), seeking: fc.boolean() }).map<PlayerEvent>(r => ({ type: 'NATIVE_PAUSE', ...r })),
  fc.constant<PlayerEvent>({ type: 'UNMUTE' }),
  fc.constant<PlayerEvent>({ type: 'ENDED' }),
  fc.record({ code: fc.constantFrom(2, 3, 4), maxRetries: fc.constant(3) }).map<PlayerEvent>(r => ({ type: 'MEDIA_ERROR', ...r })),
  fc.constant<PlayerEvent>({ type: 'CLOSE' }),
)

describe('playerMachine formal invariants (fast-check)', () => {
  it('S1-S5: holds across 1,000 randomized adversarial event interleavings', () => {
    fc.assert(
      fc.property(fc.array(arbEvent, { minLength: 1, maxLength: 60 }), (events) => {
        let state: PlayerMachineState = createInitialPlayerState()

        for (const ev of events) {
          const prev = state
          const { state: next, effect } = transitionPlayer(prev, ev)
          state = next

          // S1: Playing phase must ALWAYS report isPlaying === true.
          if (state.phase === 'playing') {
            expect(selectIsPlaying(state)).toBe(true)
          }

          // S2: Network STALLED during active unpaused playback with buffered frames (readyState >= 3, !seeking)
          // must NEVER flip isPlaying to false or get stuck buffering.
          if (
            ev.type === 'STALLED'
            && !ev.mediaPaused
            && !ev.mediaEnded
            && !ev.seeking
            && ev.readyState >= 3
            && prev.phase !== 'idle'
            && prev.phase !== 'waiting_head'
            && prev.phase !== 'error'
          ) {
            expect(selectIsPlaying(state)).toBe(true)
            expect(state.phase).toBe('playing')
          }

          // S4: Unmuted PLAY_NOT_ALLOWED while wantPlaying must trigger muted autoplay fallback.
          if (
            ev.type === 'PLAY_NOT_ALLOWED'
            && !ev.alreadyMuted
            && prev.wantPlaying
            && prev.phase !== 'idle'
            && prev.phase !== 'waiting_head'
          ) {
            expect(state.autoMutedByPolicy).toBe(true)
            expect(effect).toEqual({
              type: 'ATTEMPT_PLAY',
              mutedFallback: true,
              reason: 'not-allowed-fallback',
            })
          }

          // S5: CLOSE always resets cleanly to idle.
          if (ev.type === 'CLOSE') {
            expect(state.phase).toBe('idle')
            expect(state.wantPlaying).toBe(false)
            expect(selectIsPlaying(state)).toBe(false)
            expect(selectIsBuffering(state)).toBe(false)
          }
        }
      }),
      { numRuns: 1000 },
    )
  })

  it('Incident Replay #1: NotAllowedError after 40s head_ready triggers muted autoplay fallback', () => {
    let s = createInitialPlayerState()
    s = transitionPlayer(s, { type: 'OPEN', hash: '2ca0b43b'.repeat(5) }).state
    s = transitionPlayer(s, { type: 'HEAD_READY' }).state
    const r1 = transitionPlayer(s, { type: 'CANPLAY', mediaPaused: true })
    expect(r1.effect).toEqual({ type: 'ATTEMPT_PLAY', mutedFallback: false, reason: 'canplay' })

    // Browser rejects unmuted play() with NotAllowedError
    const r2 = transitionPlayer(r1.state, { type: 'PLAY_NOT_ALLOWED', alreadyMuted: false })
    expect(r2.state.autoMutedByPolicy).toBe(true)
    expect(r2.effect).toEqual({
      type: 'ATTEMPT_PLAY',
      mutedFallback: true,
      reason: 'not-allowed-fallback',
    })

    // Muted play succeeds -> playing with Pause button shown
    const r3 = transitionPlayer(r2.state, { type: 'PLAY_OK' })
    expect(r3.state.phase).toBe('playing')
    expect(selectIsPlaying(r3.state)).toBe(true)
  })

  it('Incident Replay #2: HTML5 stalled during playback never sticks play button in paused state', () => {
    let s = createInitialPlayerState()
    s = transitionPlayer(s, { type: 'OPEN', hash: 'ce5c7dab'.repeat(5) }).state
    s = transitionPlayer(s, { type: 'HEAD_READY' }).state
    s = transitionPlayer(s, { type: 'PLAYING' }).state
    expect(selectIsPlaying(s)).toBe(true)

    // Background Range fetch idles for 3s while video keeps playing from decoded buffer
    s = transitionPlayer(s, {
      type: 'STALLED',
      mediaPaused: false,
      mediaEnded: false,
      seeking: false,
      readyState: 4,
    }).state
    expect(selectIsPlaying(s)).toBe(true)
    expect(s.phase).toBe('playing')
    expect(selectIsBuffering(s)).toBe(false)
  })

  it('Incident Replay #3: restoreProgress seek before canplay still auto-plays on seeked', () => {
    let s = createInitialPlayerState()
    s = transitionPlayer(s, { type: 'OPEN', hash: 'f474e22d'.repeat(5) }).state
    s = transitionPlayer(s, { type: 'HEAD_READY' }).state
    // restoreProgress seeks while video is still paused (before first play)
    s = transitionPlayer(s, { type: 'SEEKING', mediaPaused: true }).state
    expect(s.wantPlaying).toBe(true)
    const r = transitionPlayer(s, { type: 'SEEKED', mediaPaused: true, mediaEnded: false })
    expect(r.effect).toEqual({ type: 'ATTEMPT_PLAY', mutedFallback: false, reason: 'seeked' })
  })
})
