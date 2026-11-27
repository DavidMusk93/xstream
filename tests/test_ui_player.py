"""Locks critical VideoModal, useVideoPlayer, and CachePanel UX invariants against regressions.

Follows tests/test_ui_star_card.py: static source assertions that catch the
exact classes of frontend regressions that broke streaming UX in production:
1. VideoModal keeps <video> persistently mounted (no v-if unmount on loading/errorMsg)
   and primes user-gesture media unlock synchronously (flush: 'sync') + muted fallback
   when browsers block unmuted autoplay after a long waitForHeadReady.
2. VideoModal openPlayback must subscribe to SSE before waitForHeadReady, and
   useVideoPlayer must resync on sse.reconnected as well as sync.resync_required.
3. VideoModal must keep isPlaying synchronized with actual HTMLMediaElement playback
   (@play, @playing, @timeupdate) and never clobber isPlaying=false inside onStalled
   or onWaiting while frames are still playing.
4. VideoModal must reportSeek on seek/seeking (not only after seeked) and
   refresh bufferedRanges via @progress.
5. CachePanel SSE handler must merge local_size and piece_segments and
   fetch metrics on mount for the header indicator dot.
"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VIDEO_MODAL = (ROOT / "frontend" / "components" / "video" / "VideoModal.vue").read_text(encoding="utf-8")
USE_VIDEO_PLAYER = (ROOT / "frontend" / "composables" / "useVideoPlayer.ts").read_text(encoding="utf-8")
PLAY_PAGE = (ROOT / "frontend" / "pages" / "play.vue").read_text(encoding="utf-8")
CACHE_PANEL = (ROOT / "frontend" / "components" / "cache" / "CachePanel.vue").read_text(encoding="utf-8")


def test_video_modal_retry_keeps_video_element_mounted():
    """Regression: <video> must stay mounted across loading/retry and delegate transitions to playerMachine."""
    video_tag = VIDEO_MODAL.split("<video", 1)[1].split("/>", 1)[0]
    assert "v-if=" not in video_tag
    assert 'v-show="isOpen"' in VIDEO_MODAL
    assert "from '~/utils/playerMachine'" in VIDEO_MODAL
    assert "transitionPlayer(" in VIDEO_MODAL
    assert "selectIsPlaying(" in VIDEO_MODAL
    assert "selectIsBuffering(" in VIDEO_MODAL


def test_video_modal_gesture_priming_and_autoplay_fallback():
    """Long head_ready waits (>5s) lose transient user activation unless primed synchronously + muted fallback."""
    assert "function primeFromUserGesture()" in VIDEO_MODAL
    assert "flush: 'sync'" in VIDEO_MODAL
    assert "NotAllowedError" in VIDEO_MODAL
    assert "autoMutedByPolicy" in VIDEO_MODAL
    assert "primeFromUserGesture()" in PLAY_PAGE


def test_video_modal_play_button_tracks_media_element_state():
    """Regression: network `stalled` / transient `waiting` must route through verified playerMachine."""
    video_tag = VIDEO_MODAL.split("<video", 1)[1].split("/>", 1)[0]
    assert '@play="onPlay"' in video_tag
    assert '@playing="onPlaying"' in video_tag
    assert '@timeupdate="onTimeUpdate"' in video_tag

    on_stalled_block = VIDEO_MODAL.split("function onStalled()", 1)[1].split("function onAbort()", 1)[0]
    assert "type: 'STALLED'" in on_stalled_block

    on_waiting_block = VIDEO_MODAL.split("function onWaiting()", 1)[1].split("function onPlaying()", 1)[0]
    assert "type: 'WAITING'" in on_waiting_block

    on_timeupdate_block = VIDEO_MODAL.split("function onTimeUpdate()", 1)[1].split("function onEnded()", 1)[0]
    assert "type: 'TIMEUPDATE'" in on_timeupdate_block


def test_video_modal_subscribes_sse_before_wait_for_head_ready():
    """Loading overlay must receive live peers/speed/cached MB while waiting for head_ready, and resync on SSE reconnect."""
    open_block = VIDEO_MODAL.split("async function openPlayback(", 1)[1].split("watch(", 1)[0]
    pos_start = open_block.index("startPolling(hash)")
    pos_wait = open_block.index("waitForHeadReady(hash)")
    assert pos_start < pos_wait
    assert USE_VIDEO_PLAYER.count("'sse.reconnected'") >= 2


def test_video_modal_reports_seek_immediately_and_tracks_progress():
    """Fast scrubbing must notify backend on seek/seeking and refresh bufferedRanges via @progress."""
    assert '@progress="onVideoProgress"' in VIDEO_MODAL
    on_seek_block = VIDEO_MODAL.split("function onSeek(", 1)[1].split("function onScrubPreview(", 1)[0]
    assert "sendSeekNow(" in on_seek_block
    on_seeking_block = VIDEO_MODAL.split("function onSeeking()", 1)[1].split("function onSeeked()", 1)[0]
    assert "sendSeekNow(" in on_seeking_block


def test_cache_panel_merges_local_size_and_piece_segments_on_sse():
    """Downloads popover must update local_size and piece_segments live from torrent.progress SSE."""
    sse_block = CACHE_PANEL.split("onServerEvent('torrent.progress'", 1)[1].split("onServerEvent('sync.resync_required'", 1)[0]
    assert "local_size" in sse_block
    assert "piece_segments" in sse_block
    assert "onMounted(" in CACHE_PANEL
    assert "getCacheMetrics()" in CACHE_PANEL.split("onMounted(", 1)[1]
