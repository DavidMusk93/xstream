#!/usr/bin/env python3
"""PieceStateTracker — piece-level download state management.

Phase 3.6 architecture:
- 3 x Python int bitmaps encode 4 states (NOT_DOWNLOADED implied by all-zero)
- O(1) head_ready via pre-computed moov mask + POPCNT (int.bit_count)
- O(1) verified_count via POPCNT
- All bit ops run at C speed (single CPU instruction for POPCNT)

Replaces filesystem-level hole scanning with O(1) piece state queries.
Syncs with libtorrent alerts to maintain accurate have_piece knowledge,
avoiding the stale-bitmap trap after service restarts.
"""
from __future__ import annotations

import enum
import os
import threading
from typing import Any

import libtorrent as lt
import xstream_core

from core import get_logger

log = get_logger("piece-tracker")


class PieceState(enum.IntEnum):
    """Download state of a single piece."""

    NOT_DOWNLOADED = 0
    DOWNLOADING = 1      # priority/deadline set, waiting for peers
    VERIFIED = 2         # hash-checked by libtorrent OR filesystem-confirmed
    CORRUPT = 3          # hash failed, needs re-download


class PieceStateTracker:
    """Track per-piece state for a single video torrent.

    Responsibilities:
    1. Initialise state from filesystem (SEEK_HOLE scan of video file range).
    2. Sync with libtorrent alerts (piece_finished, hash_failed).
    3. Provide O(1) head_ready queries via pre-computed moov mask.
    4. Provide O(1) verified_count via POPCNT.
    5. Manage play-window piece priorities.
    """

    def __init__(
        self,
        handle: lt.torrent_handle,
        video_idx: int,
        video_size: int,
        path: str,
    ) -> None:
        self.handle = handle
        self.video_idx = video_idx
        self.video_size = video_size
        self.path = path

        ti = handle.torrent_file()
        fs = ti.files()
        self.piece_length = ti.piece_length()
        self.file_offset = fs.file_offset(video_idx)
        self.num_pieces = ti.num_pieces()
        self._lock = threading.Lock()
        self._store = xstream_core.PieceStateStore(
            self.num_pieces,
            self.piece_length,
            self.file_offset,
            self.video_size,
        )
        self.start_piece = self._store.start_piece
        self.end_piece = self._store.end_piece

        # Scan filesystem once to bootstrap verified pieces.
        # This is the ONLY truth source for disk state — libtorrent's have_piece()
        # is unreliable in finished/checking states due to page-cache false positives.
        self._bootstrap_from_filesystem()

        log.debug(
            "PieceStateTracker init",
            extra={
                "start_piece": self.start_piece,
                "end_piece": self.end_piece,
                "video_pieces": self.end_piece - self.start_piece + 1,
                "verified": self.verified_count(),
            },
        )

    @property
    def _moov_vc(self) -> int:
        """Verified piece count inside the configured moov range (exposed for tests)."""
        return self._store.moov_verified_count

    # ── Pre-computation ─────────────────────────────────────

    def set_moov_range(self, moov_start: int, moov_end: int) -> None:
        """Set moov range once after _on_metadata scan. Enables O(1) head_ready."""
        self._store.set_moov_range(max(0, moov_start), max(0, moov_end))

    def set_head_tail_counts(self, head_count: int, tail_count: int) -> None:
        """Pre-compute head/tail masks for fast reset_priorities."""
        self._store.set_head_tail_counts(max(0, head_count), max(0, tail_count))

    # ── Internal helpers ────────────────────────────────────

    def _set_verified(self, piece: int) -> None:
        """Mark a single piece as VERIFIED and update moov counter."""
        if piece >= 0:
            self._store.set_verified(piece)

    def _set_corrupt(self, piece: int) -> None:
        """Mark a single piece as CORRUPT."""
        if piece >= 0:
            self._store.set_corrupt(piece)

    def _set_downloading(self, piece: int) -> None:
        """Mark a single piece as DOWNLOADING."""
        if piece >= 0:
            self._store.set_downloading(piece)

    # ── Bootstrap ───────────────────────────────────────────

    def _bootstrap_from_filesystem(self) -> None:
        """Use SEEK_HOLE to mark pieces that have data on disk.

        CRITICAL: fsync() before lseek so page-cache data is flushed.
        Without fsync, SEEK_HOLE sees only disk extents and misses
        unflushed data, producing false negatives.
        """
        if not os.path.exists(self.path):
            return

        # Flush page cache so SEEK_HOLE sees actual disk state
        try:
            fd = os.open(self.path, os.O_RDONLY)
            try:
                os.fsync(fd)
            finally:
                os.close(fd)
        except Exception as exc:
            log.warning(f"bootstrap fsync failed for {self.path}: {exc}")
            return

        try:
            fd = os.open(self.path, os.O_RDONLY)
        except OSError as exc:
            log.warning(f"bootstrap open failed for {self.path}: {exc}")
            return
        verified_pieces: list[int] = []
        try:
            offset = self.file_offset
            file_end = self.file_offset + self.video_size
            piece_len = self.piece_length

            while offset < file_end:
                piece = offset // piece_len
                piece_end = min((piece + 1) * piece_len, file_end)
                offset_in_file = offset - self.file_offset
                piece_end_in_file = piece_end - self.file_offset

                try:
                    hole = os.lseek(fd, offset_in_file, os.SEEK_HOLE)
                except OSError as exc:
                    log.warning(f"bootstrap lseek failed at {offset_in_file}: {exc}")
                    break

                if hole >= piece_end_in_file:
                    verified_pieces.append(piece)

                offset = piece_end
        finally:
            os.close(fd)
        self._store.replace_verified_pieces(verified_pieces)

    def _piece_has_data_on_disk(self, piece: int) -> bool:
        """Check if a single piece has data on disk (SEEK_HOLE after fsync)."""
        if not os.path.exists(self.path):
            return False
        try:
            fd = os.open(self.path, os.O_RDONLY)
            try:
                os.fsync(fd)
                piece_start = piece * self.piece_length
                piece_end = min((piece + 1) * self.piece_length,
                                self.file_offset + self.video_size)
                offset_in_file = piece_start - self.file_offset
                hole = os.lseek(fd, offset_in_file, os.SEEK_HOLE)
                return hole >= (piece_end - self.file_offset)
            finally:
                os.close(fd)
        except OSError:
            return False

    # ── Alert sync ──────────────────────────────────────────

    def on_piece_finished(self, piece: int) -> None:
        """Libtorrent confirmed piece hash is valid."""
        if piece >= 0 and self._store.on_piece_finished(piece):
            log.debug(
                "piece verified",
                extra={"piece": piece, "state": "verified"},
            )

    def on_hash_failed(self, piece: int) -> None:
        """Libtorrent hash check failed — data is corrupt."""
        if piece >= 0 and self._store.on_hash_failed(piece):
            log.warning(
                "piece corrupt",
                extra={"piece": piece},
            )

    # ── Queries ─────────────────────────────────────────────

    def is_verified(self, piece: int) -> bool:
        if piece < 0:
            return False
        return self._store.is_verified(piece)

    def piece_state(self, piece: int) -> PieceState:
        if piece < 0:
            return PieceState.NOT_DOWNLOADED
        return PieceState(self._store.piece_state(piece))

    def verified_count(self) -> int:
        """O(num_pieces / 64) via Rust u64::count_ones."""
        return self._store.verified_count()

    def get_lane_segments(self, segments: int = 30) -> list[list[float, float, int]]:
        """Generate lane data: split piece range into segments, each returning [start_pct, end_pct, state].

        state: 0=NOT_DOWNLOADED, 1=DOWNLOADING, 2=VERIFIED, 3=CORRUPT
        Each segment takes the most prevalent state.
        """
        if segments <= 0:
            return []
        return [
            [start_pct, end_pct, state]
            for start_pct, end_pct, state in self._store.lane_segments(segments)
        ]

    def head_ready(self) -> bool:
        """O(1) via pre-computed moov range counters in Rust."""
        return self._store.head_ready()

    # ── Actions ─────────────────────────────────────────────

    def request_pieces(self, start_piece: int, end_piece: int) -> int:
        """Set urgency on pieces that are NOT_DOWNLOADED or CORRUPT.

        Returns number of pieces newly marked DOWNLOADING.
        """
        if not self.handle.is_valid():
            return 0
        if end_piece < 0:
            return 0

        # Atomically claim non-verified, non-downloading pieces in Rust, then
        # batch-apply libtorrent priorities under self._lock.
        with self._lock:
            pieces_to_set = self._store.claim_pieces_for_download(
                max(0, start_piece), end_piece
            )
            if pieces_to_set:
                prios = list(self.handle.piece_priorities())
                for p in pieces_to_set:
                    self.handle.set_piece_deadline(p, 0)
                    if prios[p] != 7:
                        prios[p] = 7
                self.handle.prioritize_pieces(prios)
            return len(pieces_to_set)

    def request_head_tail(self, head_count: int = 30, tail_count: int = 30) -> int:
        """Request head + tail pieces (used when play starts)."""
        end = min(self.start_piece + head_count - 1, self.end_piece)
        tail_start = max(self.start_piece, self.end_piece - tail_count + 1)

        count = self.request_pieces(self.start_piece, end)
        count += self.request_pieces(tail_start, self.end_piece)
        return count

    def request_window(self, center_piece: int, window_size: int = 30) -> int:
        """Request a sliding window around the current playback position."""
        win_start = max(self.start_piece, center_piece - window_size)
        win_end = min(self.end_piece, center_piece + window_size)
        return self.request_pieces(win_start, win_end)

    def reset_priorities(self) -> None:
        """Reset all video pieces to priority 0 (used on pause/stop)."""
        if not self.handle.is_valid():
            return

        with self._lock:
            prios = list(self.handle.piece_priorities())
            changed = False
            for p in range(self.start_piece, self.end_piece + 1):
                if prios[p] > 0:
                    prios[p] = 0
                    changed = True
            if changed:
                self.handle.prioritize_pieces(prios)
            self._store.clear_downloading()
