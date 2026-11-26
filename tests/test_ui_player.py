"""Locks critical VideoModal and CachePanel UX invariants against regressions.

Follows tests/test_ui_star_card.py: static source assertions that catch the
exact classes of frontend regressions that broke streaming UX in production:
1. VideoModal onError retry must never set errorMsg (which unmounts <video>).
2. VideoModal openPlayback must subscribe to SSE before waitForHeadReady.
3. VideoModal must reportSeek on seek/seeking (not only after seeked) and
   refresh bufferedRanges via @progress.
4. CachePanel SSE handler must merge local_size and piece_segments and
   fetch metrics on mount for the header indicator dot.
"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VIDEO_MODAL = (ROOT / "frontend" / "components" / "video" / "VideoModal.vue").read_text(encoding="utf-8")
CACHE_PANEL = (ROOT / "frontend" / "components" / "cache" / "CachePanel.vue").read_text(encoding="utf-8")


def test_video_modal_retry_keeps_video_element_mounted():
    """Regression: setting errorMsg during retry unmounted <video v-if='!loading && !errorMsg'>."""
    assert 'v-if="!loading && !errorMsg"' in VIDEO_MODAL
    on_error_block = VIDEO_MODAL.split("function onError()", 1)[1].split("function togglePlay()", 1)[0]
    retry_branches = on_error_block.split("if (retryCount.value < MAX_RETRIES)")
    assert len(retry_branches) >= 2
    # Inside the retry branches, retryingMsg must be used instead of errorMsg
    first_retry = on_error_block.split("if (code === 4 && retryCount.value < MAX_RETRIES)", 1)[1].split("return", 1)[0]
    assert "errorMsg.value =" not in first_retry
    assert "retryingMsg.value =" in first_retry

    second_retry = retry_branches[1].split("return", 1)[0]
    assert "errorMsg.value =" not in second_retry
    assert "retryingMsg.value =" in second_retry


def test_video_modal_subscribes_sse_before_wait_for_head_ready():
    """Loading overlay must receive live peers/speed/cached MB while waiting for head_ready."""
    open_block = VIDEO_MODAL.split("async function openPlayback(", 1)[1].split("watch(", 1)[0]
    pos_start = open_block.index("startPolling(hash)")
    pos_wait = open_block.index("waitForHeadReady(hash)")
    assert pos_start < pos_wait


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
