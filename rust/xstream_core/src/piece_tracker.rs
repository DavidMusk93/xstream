//! Thread-safe piece-level download state machine backed by compact `u64` bitsets.
//!
//! Ported from `backend/services/piece_tracker.py` following `rust-port` and
//! `rust-best-practices`. All four piece states are mutually exclusive and
//! guarded by a single mutex alongside the pre-computed `moov` counters so
//! `head_ready()` and `verified_count()` stay consistent under concurrent
//! alert, stream, and bootstrap callers.

use std::fmt;
use std::ops::RangeInclusive;
use std::sync::Mutex;

/// Download state of a single `BitTorrent` piece.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash)]
#[non_exhaustive]
#[repr(u8)]
pub enum PieceState {
    /// No verified data on disk and not currently requested.
    NotDownloaded = 0,
    /// Priority/deadline set; waiting for peers.
    Downloading = 1,
    /// Hash-checked by libtorrent or confirmed on disk via `SEEK_HOLE`.
    Verified = 2,
    /// Hash check failed; eligible for re-request.
    Corrupt = 3,
}

impl PieceState {
    /// Returns the numeric discriminant matching Python's `PieceState(IntEnum)`.
    pub fn as_u8(self) -> u8 {
        match self {
            Self::NotDownloaded => 0,
            Self::Downloading => 1,
            Self::Verified => 2,
            Self::Corrupt => 3,
        }
    }
}

/// Geometry of a video file inside a torrent.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct PieceLayout {
    /// Total number of pieces in the torrent.
    pub num_pieces: usize,
    /// Byte length of each full piece.
    pub piece_length: u64,
    /// Byte offset of the video file within the torrent.
    pub file_offset: u64,
    /// Byte size of the video file.
    pub video_size: u64,
}

/// Validation errors when constructing a [`PieceStateStore`].
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
#[non_exhaustive]
pub enum TrackerError {
    /// `piece_length` was zero.
    ZeroPieceLength,
    /// `num_pieces` was zero.
    ZeroPieces,
    /// `video_size` was zero.
    ZeroVideoSize,
    /// Computed `start_piece` exceeds the torrent's piece count.
    FileOffsetOutOfRange,
}

impl fmt::Display for TrackerError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::ZeroPieceLength => f.write_str("piece length must be non-zero"),
            Self::ZeroPieces => f.write_str("torrent must contain at least one piece"),
            Self::ZeroVideoSize => f.write_str("video size must be non-zero"),
            Self::FileOffsetOutOfRange => f.write_str("video file offset exceeds torrent pieces"),
        }
    }
}

impl std::error::Error for TrackerError {}

/// One bucket in the progress-bar lane visualization.
#[derive(Debug, Clone, Copy, PartialEq)]
pub struct LaneSegment {
    /// Segment start percentage in `[0.0, 100.0]`, rounded to 2 decimal places.
    pub start_pct: f64,
    /// Segment end percentage in `[0.0, 100.0]`, rounded to 2 decimal places.
    pub end_pct: f64,
    /// Dominant [`PieceState`] in this segment.
    pub state: PieceState,
}

/// Compact `u64`-word bitset for piece indices in `0..num_pieces`.
#[derive(Debug, Clone)]
struct Bitset {
    words: Vec<u64>,
}

impl Bitset {
    fn new(num_pieces: usize) -> Self {
        let word_count = num_pieces.div_ceil(64);
        Self {
            words: vec![0; word_count],
        }
    }

    fn clear_all(&mut self) {
        self.words.fill(0);
    }

    fn get(&self, idx: usize) -> bool {
        let word = idx / 64;
        let bit = idx % 64;
        self.words
            .get(word)
            .is_some_and(|w| (w & (1_u64 << bit)) != 0)
    }

    /// Sets bit `idx` and returns whether it was previously set.
    fn set(&mut self, idx: usize) -> bool {
        let word = idx / 64;
        let bit = idx % 64;
        if let Some(w) = self.words.get_mut(word) {
            let mask = 1_u64 << bit;
            let was = (*w & mask) != 0;
            *w |= mask;
            was
        } else {
            false
        }
    }

    /// Clears bit `idx` and returns whether it was previously set.
    fn clear(&mut self, idx: usize) -> bool {
        let word = idx / 64;
        let bit = idx % 64;
        if let Some(w) = self.words.get_mut(word) {
            let mask = 1_u64 << bit;
            let was = (*w & mask) != 0;
            *w &= !mask;
            was
        } else {
            false
        }
    }

    fn count_ones(&self) -> usize {
        self.words
            .iter()
            .map(|w| usize::try_from(w.count_ones()).unwrap_or(0))
            .sum()
    }

    fn count_ones_in_range(&self, range: &RangeInclusive<usize>) -> usize {
        let start = *range.start();
        let end = *range.end();
        if start > end || self.words.is_empty() {
            return 0;
        }
        let max_idx = self.words.len() * 64 - 1;
        let clamped_end = end.min(max_idx);
        if start > clamped_end {
            return 0;
        }
        let start_word = start / 64;
        let end_word = clamped_end / 64;
        let mut total = 0_usize;
        for wi in start_word..=end_word {
            let mut mask = u64::MAX;
            if wi == start_word {
                let lo = start % 64;
                mask &= u64::MAX << lo;
            }
            if wi == end_word {
                let hi = clamped_end % 64;
                mask &= u64::MAX >> (63 - hi);
            }
            let ones = (self.words[wi] & mask).count_ones();
            total += usize::try_from(ones).unwrap_or(0);
        }
        total
    }
}

#[derive(Debug)]
struct Inner {
    verified: Bitset,
    corrupt: Bitset,
    downloading: Bitset,
    moov_range: Option<RangeInclusive<usize>>,
    moov_piece_count: usize,
    moov_verified_count: usize,
    head_range: Option<RangeInclusive<usize>>,
    tail_range: Option<RangeInclusive<usize>>,
}

impl Inner {
    fn new(num_pieces: usize) -> Self {
        Self {
            verified: Bitset::new(num_pieces),
            corrupt: Bitset::new(num_pieces),
            downloading: Bitset::new(num_pieces),
            moov_range: None,
            moov_piece_count: 0,
            moov_verified_count: 0,
            head_range: None,
            tail_range: None,
        }
    }

    fn in_moov(&self, piece: usize) -> bool {
        self.moov_range.as_ref().is_some_and(|r| r.contains(&piece))
    }

    fn set_verified(&mut self, piece: usize) {
        if self.verified.set(piece) {
            return;
        }
        self.corrupt.clear(piece);
        self.downloading.clear(piece);
        if self.in_moov(piece) {
            self.moov_verified_count += 1;
        }
    }

    fn set_corrupt(&mut self, piece: usize) {
        let was_verified = self.verified.clear(piece);
        self.corrupt.set(piece);
        self.downloading.clear(piece);
        if was_verified && self.in_moov(piece) {
            self.moov_verified_count = self.moov_verified_count.saturating_sub(1);
        }
    }

    fn set_downloading(&mut self, piece: usize) {
        let was_verified = self.verified.clear(piece);
        self.downloading.set(piece);
        self.corrupt.clear(piece);
        if was_verified && self.in_moov(piece) {
            self.moov_verified_count = self.moov_verified_count.saturating_sub(1);
        }
    }

    fn piece_state(&self, piece: usize) -> PieceState {
        if self.verified.get(piece) {
            PieceState::Verified
        } else if self.corrupt.get(piece) {
            PieceState::Corrupt
        } else if self.downloading.get(piece) {
            PieceState::Downloading
        } else {
            PieceState::NotDownloaded
        }
    }
}

/// Thread-safe per-piece state store for a single video torrent.
#[derive(Debug)]
pub struct PieceStateStore {
    layout: PieceLayout,
    start_piece: usize,
    end_piece: usize,
    inner: Mutex<Inner>,
}

const _: () = {
    const fn assert_send_sync<T: Send + Sync>() {}
    assert_send_sync::<PieceStateStore>();
};

impl PieceStateStore {
    /// Creates a new store with all pieces initialized to [`PieceState::NotDownloaded`].
    ///
    /// # Errors
    ///
    /// Returns [`TrackerError`] if `piece_length`, `num_pieces`, or `video_size` is
    /// zero, or if `file_offset` starts past the last piece.
    pub fn try_new(layout: PieceLayout) -> Result<Self, TrackerError> {
        if layout.piece_length == 0 {
            return Err(TrackerError::ZeroPieceLength);
        }
        if layout.num_pieces == 0 {
            return Err(TrackerError::ZeroPieces);
        }
        if layout.video_size == 0 {
            return Err(TrackerError::ZeroVideoSize);
        }

        let start_u64 = layout.file_offset / layout.piece_length;
        let start_piece =
            usize::try_from(start_u64).map_err(|_| TrackerError::FileOffsetOutOfRange)?;
        if start_piece >= layout.num_pieces {
            return Err(TrackerError::FileOffsetOutOfRange);
        }

        let last_byte = layout.file_offset.saturating_add(layout.video_size - 1);
        let raw_end =
            usize::try_from(last_byte / layout.piece_length).unwrap_or(layout.num_pieces - 1);
        let end_piece = raw_end.min(layout.num_pieces - 1);

        Ok(Self {
            layout,
            start_piece,
            end_piece,
            inner: Mutex::new(Inner::new(layout.num_pieces)),
        })
    }

    /// Returns the video layout geometry.
    pub fn layout(&self) -> PieceLayout {
        self.layout
    }

    /// Returns the first torrent piece intersecting the video file.
    pub fn start_piece(&self) -> usize {
        self.start_piece
    }

    /// Returns the last torrent piece intersecting the video file (inclusive).
    pub fn end_piece(&self) -> usize {
        self.end_piece
    }

    /// Configures the `moov` byte range (relative to the video file start) for
    /// `O(1)` [`head_ready`](Self::head_ready) queries.
    ///
    /// # Panics
    ///
    /// Panics if the internal mutex is poisoned.
    pub fn set_moov_range(&self, moov_start: u64, moov_end: u64) {
        if moov_end <= moov_start {
            return;
        }
        let sp = usize::try_from((self.layout.file_offset + moov_start) / self.layout.piece_length)
            .unwrap_or(self.layout.num_pieces - 1);
        let ep =
            usize::try_from((self.layout.file_offset + moov_end - 1) / self.layout.piece_length)
                .unwrap_or(self.layout.num_pieces - 1);
        if ep < sp {
            return;
        }
        let range = sp..=ep;
        let mut inner = self.inner.lock().expect("piece tracker lock poisoned");
        inner.moov_piece_count = ep - sp + 1;
        inner.moov_verified_count = inner.verified.count_ones_in_range(&range);
        inner.moov_range = Some(range);
    }

    /// Pre-computes head and tail piece ranges.
    ///
    /// # Panics
    ///
    /// Panics if the internal mutex is poisoned.
    pub fn set_head_tail_counts(&self, head_count: usize, tail_count: usize) {
        let mut inner = self.inner.lock().expect("piece tracker lock poisoned");
        inner.head_range = if head_count == 0 {
            None
        } else {
            let head_end = self
                .start_piece
                .saturating_add(head_count - 1)
                .min(self.end_piece);
            Some(self.start_piece..=head_end)
        };
        inner.tail_range = if tail_count == 0 {
            None
        } else {
            let tail_start = self
                .end_piece
                .saturating_sub(tail_count - 1)
                .max(self.start_piece);
            Some(tail_start..=self.end_piece)
        };
    }

    /// Replaces all bitmap state with a fresh set of disk-verified pieces
    /// (called after `SEEK_HOLE` bootstrap). Clears `corrupt` and `downloading`
    /// and recomputes `moov_verified_count`.
    ///
    /// # Panics
    ///
    /// Panics if the internal mutex is poisoned.
    pub fn replace_verified_pieces<I: IntoIterator<Item = usize>>(&self, pieces: I) {
        let mut inner = self.inner.lock().expect("piece tracker lock poisoned");
        inner.verified.clear_all();
        inner.corrupt.clear_all();
        inner.downloading.clear_all();
        for p in pieces {
            if p < self.layout.num_pieces {
                inner.verified.set(p);
            }
        }
        inner.moov_verified_count = inner
            .moov_range
            .as_ref()
            .map_or(0, |r| inner.verified.count_ones_in_range(r));
    }

    /// Marks a single piece as [`PieceState::Verified`] regardless of video bounds
    /// (preserves Python `_set_verified` behavior for tests).
    ///
    /// # Panics
    ///
    /// Panics if the internal mutex is poisoned.
    pub fn set_verified(&self, piece: usize) {
        if piece >= self.layout.num_pieces {
            return;
        }
        let mut inner = self.inner.lock().expect("piece tracker lock poisoned");
        inner.set_verified(piece);
    }

    /// Marks a single piece as [`PieceState::Corrupt`].
    ///
    /// # Panics
    ///
    /// Panics if the internal mutex is poisoned.
    pub fn set_corrupt(&self, piece: usize) {
        if piece >= self.layout.num_pieces {
            return;
        }
        let mut inner = self.inner.lock().expect("piece tracker lock poisoned");
        inner.set_corrupt(piece);
    }

    /// Marks a single piece as [`PieceState::Downloading`].
    ///
    /// # Panics
    ///
    /// Panics if the internal mutex is poisoned.
    pub fn set_downloading(&self, piece: usize) {
        if piece >= self.layout.num_pieces {
            return;
        }
        let mut inner = self.inner.lock().expect("piece tracker lock poisoned");
        inner.set_downloading(piece);
    }

    /// Handles libtorrent `piece_finished_alert` (ignores pieces outside video bounds).
    ///
    /// # Panics
    ///
    /// Panics if the internal mutex is poisoned.
    pub fn on_piece_finished(&self, piece: usize) -> bool {
        if piece < self.start_piece || piece > self.end_piece {
            return false;
        }
        let mut inner = self.inner.lock().expect("piece tracker lock poisoned");
        inner.set_verified(piece);
        true
    }

    /// Handles libtorrent `hash_failed_alert` (ignores pieces outside video bounds).
    ///
    /// # Panics
    ///
    /// Panics if the internal mutex is poisoned.
    pub fn on_hash_failed(&self, piece: usize) -> bool {
        if piece < self.start_piece || piece > self.end_piece {
            return false;
        }
        let mut inner = self.inner.lock().expect("piece tracker lock poisoned");
        inner.set_corrupt(piece);
        true
    }

    /// Returns whether `piece` is currently [`PieceState::Verified`].
    ///
    /// # Panics
    ///
    /// Panics if the internal mutex is poisoned.
    pub fn is_verified(&self, piece: usize) -> bool {
        if piece >= self.layout.num_pieces {
            return false;
        }
        let inner = self.inner.lock().expect("piece tracker lock poisoned");
        inner.verified.get(piece)
    }

    /// Returns the current [`PieceState`] of `piece` (`NotDownloaded` if out of range).
    ///
    /// # Panics
    ///
    /// Panics if the internal mutex is poisoned.
    pub fn piece_state(&self, piece: usize) -> PieceState {
        if piece >= self.layout.num_pieces {
            return PieceState::NotDownloaded;
        }
        let inner = self.inner.lock().expect("piece tracker lock poisoned");
        inner.piece_state(piece)
    }

    /// Returns the total number of verified pieces (`O(num_pieces / 64)` via `count_ones`).
    ///
    /// # Panics
    ///
    /// Panics if the internal mutex is poisoned.
    pub fn verified_count(&self) -> usize {
        let inner = self.inner.lock().expect("piece tracker lock poisoned");
        inner.verified.count_ones()
    }

    /// Returns the number of verified pieces inside the configured `moov` range.
    ///
    /// # Panics
    ///
    /// Panics if the internal mutex is poisoned.
    pub fn moov_verified_count(&self) -> usize {
        let inner = self.inner.lock().expect("piece tracker lock poisoned");
        inner.moov_verified_count
    }

    /// Returns `true` iff a `moov` range is configured and every piece in it is verified.
    ///
    /// # Panics
    ///
    /// Panics if the internal mutex is poisoned.
    pub fn head_ready(&self) -> bool {
        let inner = self.inner.lock().expect("piece tracker lock poisoned");
        inner.moov_piece_count > 0 && inner.moov_verified_count == inner.moov_piece_count
    }

    /// Identifies pieces in `[req_start, req_end]` (clamped to video bounds) that
    /// are neither `Verified` nor `Downloading` (so `NotDownloaded` and `Corrupt`
    /// pieces are returned), and marks them `Downloading` atomically.
    ///
    /// # Panics
    ///
    /// Panics if the internal mutex is poisoned.
    pub fn claim_pieces_for_download(&self, req_start: usize, req_end: usize) -> Vec<usize> {
        let start = req_start.max(self.start_piece);
        let end = req_end.min(self.end_piece);
        if start > end {
            return Vec::new();
        }
        let mut inner = self.inner.lock().expect("piece tracker lock poisoned");
        let mut claimed = Vec::new();
        for p in start..=end {
            if !inner.verified.get(p) && !inner.downloading.get(p) {
                inner.set_downloading(p);
                claimed.push(p);
            }
        }
        claimed
    }

    /// Clears all `Downloading` bits (called on pause/stop when priorities are reset).
    ///
    /// # Panics
    ///
    /// Panics if the internal mutex is poisoned.
    pub fn clear_downloading(&self) {
        let mut inner = self.inner.lock().expect("piece tracker lock poisoned");
        inner.downloading.clear_all();
    }

    /// Splits the video piece range into `segments` buckets for progress-bar display.
    ///
    /// Ties break with priority `Verified > Downloading > Corrupt > NotDownloaded`,
    /// matching the original Python implementation.
    ///
    /// # Panics
    ///
    /// Panics if the internal mutex is poisoned.
    pub fn lane_segments(&self, segments: usize) -> Vec<LaneSegment> {
        if segments == 0 {
            return Vec::new();
        }
        let total_pieces = self.end_piece.saturating_sub(self.start_piece) + 1;
        let inner = self.inner.lock().expect("piece tracker lock poisoned");
        let mut result = Vec::with_capacity(segments);
        #[expect(
            clippy::as_conversions,
            clippy::cast_precision_loss,
            reason = "segment ratios and percentage calculations are bounded UI values"
        )]
        let seg_size = (total_pieces as f64) / (segments as f64);
        #[expect(
            clippy::as_conversions,
            clippy::cast_precision_loss,
            reason = "segment count is small (typically 30)"
        )]
        let seg_total_f = segments as f64;

        for seg in 0..segments {
            #[expect(
                clippy::as_conversions,
                clippy::cast_precision_loss,
                reason = "loop index is bounded by segments"
            )]
            let seg_f = seg as f64;
            #[expect(
                clippy::as_conversions,
                clippy::cast_possible_truncation,
                clippy::cast_sign_loss,
                reason = "seg_f * seg_size is non-negative and bounded by total_pieces"
            )]
            let seg_start_piece = self.start_piece + (seg_f * seg_size) as usize;
            #[expect(
                clippy::as_conversions,
                clippy::cast_possible_truncation,
                clippy::cast_sign_loss,
                reason = "(seg_f + 1.0) * seg_size is non-negative and bounded by total_pieces"
            )]
            let next_start = self.start_piece + ((seg_f + 1.0) * seg_size) as usize;
            let seg_end_piece = if seg + 1 == segments {
                self.end_piece
            } else {
                next_start.saturating_sub(1)
            };

            let mut counts = [0_usize; 4];
            if seg_start_piece <= seg_end_piece {
                for p in seg_start_piece..=seg_end_piece {
                    let st = inner.piece_state(p);
                    counts[usize::from(st.as_u8())] += 1;
                }
            }

            // Preserve original tie-break order: iterate (2, 1, 3) with >= against counts[0]
            let mut best_state = PieceState::NotDownloaded;
            let mut best_count = counts[0];
            for state in [
                PieceState::Verified,
                PieceState::Downloading,
                PieceState::Corrupt,
            ] {
                let c = counts[usize::from(state.as_u8())];
                if c >= best_count {
                    best_count = c;
                    best_state = state;
                }
            }

            let start_pct = (seg_f / seg_total_f * 100.0 * 100.0).round() / 100.0;
            let end_pct = ((seg_f + 1.0) / seg_total_f * 100.0 * 100.0).round() / 100.0;
            result.push(LaneSegment {
                start_pct,
                end_pct,
                state: best_state,
            });
        }

        result
    }
}

#[cfg(test)]
mod tests {
    use std::sync::Arc;
    use std::thread;

    use super::*;

    fn default_layout(num_pieces: usize, file_offset: u64) -> PieceLayout {
        let piece_length = 2_097_152;
        let total = u64::try_from(num_pieces).expect("num_pieces fits u64") * piece_length;
        PieceLayout {
            num_pieces,
            piece_length,
            file_offset,
            video_size: total - file_offset,
        }
    }

    // ── Ported from tests/test_piece_tracker.py ──────────────────────────

    #[test]
    fn piece_state_enum_discriminants_match_python() {
        assert_eq!(PieceState::NotDownloaded.as_u8(), 0);
        assert_eq!(PieceState::Downloading.as_u8(), 1);
        assert_eq!(PieceState::Verified.as_u8(), 2);
        assert_eq!(PieceState::Corrupt.as_u8(), 3);
    }

    // ── Ported from tests/test_piece_tracker_regression.py ───────────────

    #[test]
    fn claim_head_tail_skips_already_verified_and_downloading() {
        let store = PieceStateStore::try_new(default_layout(100, 512)).unwrap();
        store.set_head_tail_counts(5, 5);
        let head = store.claim_pieces_for_download(0, 4);
        let tail = store.claim_pieces_for_download(95, 99);
        assert_eq!(head, vec![0, 1, 2, 3, 4]);
        assert_eq!(tail, vec![95, 96, 97, 98, 99]);
        // Re-requesting already-downloading pieces returns empty
        assert_eq!(store.claim_pieces_for_download(0, 4), Vec::<usize>::new());
    }

    #[test]
    fn corrupt_pieces_are_re_claimed_for_download() {
        let store = PieceStateStore::try_new(default_layout(20, 0)).unwrap();
        store.set_corrupt(3);
        assert_eq!(store.piece_state(3), PieceState::Corrupt);
        let claimed = store.claim_pieces_for_download(2, 4);
        assert_eq!(claimed, vec![2, 3, 4]);
        assert_eq!(store.piece_state(3), PieceState::Downloading);
    }

    #[test]
    fn verified_pieces_are_not_re_claimed() {
        let store = PieceStateStore::try_new(default_layout(20, 0)).unwrap();
        store.on_piece_finished(2);
        store.on_piece_finished(3);
        let claimed = store.claim_pieces_for_download(2, 4);
        assert_eq!(claimed, vec![4]);
        assert_eq!(store.piece_state(2), PieceState::Verified);
        assert_eq!(store.piece_state(3), PieceState::Verified);
        assert_eq!(store.piece_state(4), PieceState::Downloading);
    }

    #[test]
    fn tail_moov_fallback_tracks_tail_pieces() {
        let store = PieceStateStore::try_new(default_layout(100, 512)).unwrap();
        let pl = store.layout().piece_length;
        let tail_start = store
            .end_piece()
            .saturating_sub(29)
            .max(store.start_piece());
        let moov_start = u64::try_from(tail_start).unwrap() * pl - store.layout().file_offset;
        let moov_end =
            u64::try_from(store.end_piece() + 1).unwrap() * pl - store.layout().file_offset - 1;
        store.set_moov_range(moov_start, moov_end);

        assert!(!store.head_ready());
        for p in tail_start..=store.end_piece() {
            store.set_verified(p);
        }
        assert!(store.head_ready());
    }

    #[test]
    fn set_corrupt_only_decrements_moov_vc_when_was_verified() {
        let store = PieceStateStore::try_new(default_layout(20, 512)).unwrap();
        let pl = store.layout().piece_length;
        store.set_moov_range(3 * pl, 4 * pl);

        store.set_corrupt(3);
        assert_eq!(store.moov_verified_count(), 0);
        assert_eq!(store.piece_state(3), PieceState::Corrupt);
    }

    #[test]
    fn set_corrupt_decrements_moov_vc_when_was_verified() {
        let store = PieceStateStore::try_new(default_layout(20, 512)).unwrap();
        let pl = store.layout().piece_length;
        store.set_moov_range(3 * pl, 4 * pl);

        store.set_verified(3);
        assert_eq!(store.moov_verified_count(), 1);
        store.set_corrupt(3);
        assert_eq!(store.moov_verified_count(), 0);
        assert_eq!(store.piece_state(3), PieceState::Corrupt);
    }

    #[test]
    fn repeated_corrupt_never_underflows_moov_vc() {
        let store = PieceStateStore::try_new(default_layout(20, 512)).unwrap();
        let pl = store.layout().piece_length;
        store.set_moov_range(3 * pl, 4 * pl);

        store.set_verified(3);
        assert_eq!(store.moov_verified_count(), 1);
        store.set_corrupt(3);
        store.set_corrupt(3);
        store.set_corrupt(3);
        assert_eq!(store.moov_verified_count(), 0);
    }

    #[test]
    fn set_downloading_decrements_moov_vc_when_clearing_verified() {
        let store = PieceStateStore::try_new(default_layout(20, 512)).unwrap();
        let pl = store.layout().piece_length;
        store.set_moov_range(3 * pl, 4 * pl);

        store.set_verified(3);
        assert_eq!(store.moov_verified_count(), 1);
        store.set_downloading(3);
        assert_eq!(store.moov_verified_count(), 0);
        assert_eq!(store.piece_state(3), PieceState::Downloading);
    }

    #[test]
    fn replace_verified_resets_state_and_updates_moov_vc() {
        let store = PieceStateStore::try_new(default_layout(20, 512)).unwrap();
        let pl = store.layout().piece_length;
        store.set_moov_range(3 * pl, 4 * pl);

        store.set_verified(3);
        assert_eq!(store.moov_verified_count(), 1);

        store.replace_verified_pieces([]);
        assert_eq!(store.piece_state(3), PieceState::NotDownloaded);
        assert_eq!(store.moov_verified_count(), 0);
        assert_eq!(store.verified_count(), 0);
    }

    #[test]
    fn lane_segments_matches_expected_buckets_and_tie_break() {
        let store = PieceStateStore::try_new(default_layout(10, 0)).unwrap();
        store.on_piece_finished(0);
        store.on_piece_finished(1);
        store.set_downloading(5);
        let segs = store.lane_segments(5);
        assert_eq!(segs.len(), 5);
        assert_eq!(segs[0].state, PieceState::Verified);
        assert!((segs[0].start_pct - 0.0).abs() < f64::EPSILON);
        assert!((segs[0].end_pct - 20.0).abs() < f64::EPSILON);
        // Bucket 2 covers pieces 4..=5 (1 NotDownloaded, 1 Downloading -> Downloading wins tie)
        assert_eq!(segs[2].state, PieceState::Downloading);
        assert_eq!(segs[4].state, PieceState::NotDownloaded);
    }

    #[test]
    fn concurrent_alert_and_query_stress() {
        let store = Arc::new(PieceStateStore::try_new(default_layout(512, 0)).unwrap());
        let pl = store.layout().piece_length;
        store.set_moov_range(0, 64 * pl);

        let mut handles = Vec::new();
        for t in 0..4 {
            let s = Arc::clone(&store);
            handles.push(thread::spawn(move || {
                for p in (t..512).step_by(4) {
                    let _ = s.claim_pieces_for_download(p, p);
                    s.on_piece_finished(p);
                    let _ = s.head_ready();
                    let _ = s.verified_count();
                }
            }));
        }
        for h in handles {
            h.join().unwrap();
        }
        assert_eq!(store.verified_count(), 512);
        assert_eq!(store.moov_verified_count(), 64);
        assert!(store.head_ready());
    }
}
