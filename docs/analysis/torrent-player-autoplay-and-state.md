# RCA: Torrent Player Autoplay Failure & Stuck Play/Pause Button

> **Date:** 2026-11-26  
> **Components:** `frontend/components/video/VideoModal.vue`, `frontend/composables/useVideoPlayer.ts`, `frontend/pages/play.vue`, `rust/xstream_bt/src/{engine,main}.rs`

---

## Symptoms

1. **No autoplay once enough data is buffered (`head_ready`)**: after the loading overlay finished (`10 MiB` contiguous head + `4 MiB` tail), `<video>` stayed frozen at `0:00` until manually tapped, or hung waiting on brand-new magnets whose metadata arrived asynchronously.
2. **Play button stuck in paused (`▶`) state during active playback**: while frames and audio played normally and `POST /torrent/progress` fired every 10s, the transport button displayed `▶` (`isPlaying === false`) instead of `⏸`.

---

## Root Causes

### 1. Unmounted `<video>` + Lost User-Gesture Activation (`NotAllowedError`)

Production client logs (`logs/frontend.log`) captured repeated rejections whenever `waitForHeadReady` exceeded WebKit/Blink's ~5s transient activation window (e.g. `11.9s` on `MIDA-874`, `40.7s` on `IDPC-039`):

```text
[player] canplay play() rejected: NotAllowedError
```

- `VideoModal.vue` rendered `<div v-if="isOpen">` and `<video v-if="!loading && !errorMsg">`.
- While `loading` was `true` during `waitForHeadReady`, **no `<video>` element existed in the DOM**.
- Once `head_ready` arrived 10-45s later, Vue mounted a brand-new, unblessed `<video>` outside any user gesture; WebKit/mobile browsers rejected unmuted `v.play()` with `NotAllowedError` and left playback paused.
- Additionally:
  - `restoreProgress()` inside `onLoadedMetadata` seeked before playback started, firing `onSeeking()` while `isPlaying` was `false` (`wasPlayingBeforeSeek = false`), so `onSeeked()` skipped `v.play()`.
  - `useVideoPlayer.ts` did not subscribe to `sse.reconnected`, so a `torrent.head_ready` pushed during a 1s mobile SSE drop could be missed.
  - `xstream_bt` only called `ensure_head_prewarm` during initial `add_magnet`/`resume`; for cold magnets whose info-dict resolved seconds later (`ready: false -> true`), `only_files = []` had no prewarm cursor attached until another API call arrived.

### 2. HTML5 `stalled` / `waiting` Clobbering `isPlaying`

- `onStalled()` unconditionally set `isPlaying.value = false` and `buffering.value = true`.
- Per the HTML5 media specification, `stalled` is a **network fetch** event (no bytes received on the background HTTP Range socket for ~3s), **not** a playback pause: `<video>` continues rendering smoothly from its decoded buffer (`v.paused === false`, `timeupdate` advancing) and therefore **never fires `@playing` again**.
- `@play` was not bound on `<video>`, and `onTimeUpdate` never reconciled `isPlaying` with `!v.paused && !v.ended`, leaving `isPlaying` permanently stuck at `false` for the rest of playback.

---

## Fixes

1. **Persistent `<video>` + Synchronous Gesture Priming + Muted Fallback**:
   - Keep `.player-root` (`v-show="isOpen"`) and `<video>` mounted across `loading` and retry states so the element reference survives async `waitForHeadReady`.
   - Run `primeFromUserGesture()` synchronously inside the user's tap/submit call stack (`watch(isOpen, ..., { flush: 'sync' })` and `videoModalRef.primeFromUserGesture()` on `/play`) to unlock per-element WebKit media playback before async waiting.
   - Separate playback intent (`wantPlaying`) from media state (`isPlaying`), and if a browser still rejects unmuted `play()` with `NotAllowedError`, automatically start muted playback with a one-tap `"Tap to unmute"` pill.
2. **Authoritative `isPlaying` Synchronization**:
   - Derive `isPlaying` from `!v.paused && !v.ended` (`syncPlayingState()`), bind `@play="onPlay"`, reconcile inside `onTimeUpdate`, and never force `isPlaying = false` in `onStalled` or `onWaiting`.
3. **Non-Blocking Magnet Add, Late-Metadata Prewarm & SSE Reconnect Resync**:
   - Detach `librqbit::Session::add_torrent` onto a background task (`pending_adds`) with a 200ms fast-path so cold DHT magnets (>15s metadata lookup) return HTTP 200 immediately instead of timing out `bt_client.add_torrent` (503) and dropping the Axum future; `status()` reports `"downloading_metadata"` (`Fetching metadata` in UI) while keeping `bt_client._watch_hash` alive.
   - Add a 1s `ensure_active_prewarms()` pass in `xstream_bt` so newly resolved `Live` magnets immediately enter strict on-demand mode and open head+tail prewarm cursors.
   - Resync `checkHeadReady` / `pollStatus` on `sse.reconnected` in `useVideoPlayer.ts`.
