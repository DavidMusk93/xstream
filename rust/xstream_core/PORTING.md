# Porting Notes: `PieceStateTracker` → `xstream_core::piece_tracker`

## API Mapping

| Python (`backend/services/piece_tracker.py`) | Rust (`rust/xstream_core/src/piece_tracker.rs`) |
|---|---|
| `PieceState(IntEnum)` | `PieceState` (`#[non_exhaustive]`, `#[repr(u8)]`, `as_u8()`) |
| `PieceStateTracker.__init__` geometry + bitmaps | `PieceStateStore::try_new(PieceLayout)` (`Result<_, TrackerError>`) |
| `set_moov_range(start, end)` | `PieceStateStore::set_moov_range(u64, u64)` |
| `set_head_tail_counts(h, t)` | `PieceStateStore::set_head_tail_counts(usize, usize)` |
| `_set_verified` / `_set_corrupt` / `_set_downloading` | `set_verified` / `set_corrupt` / `set_downloading` |
| `on_piece_finished` / `on_hash_failed` | `on_piece_finished` / `on_hash_failed` |
| `is_verified` / `piece_state` / `verified_count` / `head_ready` | Same names on `PieceStateStore` |
| `get_lane_segments(segments)` | `lane_segments(usize) -> Vec<LaneSegment>` |
| `request_pieces` bitmap planning | `claim_pieces_for_download(usize, usize) -> Vec<usize>` |
| `reset_priorities` downloading clear | `clear_downloading()` |
| `_bootstrap_from_filesystem` bitmap reset + set | `replace_verified_pieces(IntoIterator<Item = usize>)` |

## Test Mapping

| Python test | Rust unit test |
|---|---|
| `test_piece_tracker.py::test_not_downloaded_to_downloading` | `piece_state_enum_discriminants_match_python` |
| `test_piece_tracker_regression.py::test_prioritize_pieces_sets_tail_to_7` | `claim_head_tail_skips_already_verified_and_downloading` |
| `test_piece_tracker_regression.py::test_have_piece_true_becomes_verified_not_downloading` | `verified_pieces_are_not_re_claimed` |
| `test_piece_tracker_regression.py::test_fallback_moov_range_tracks_tail` | `tail_moov_fallback_tracks_tail_pieces` |
| `test_piece_tracker_regression.py::test_set_corrupt_only_decrements_when_was_verified` | `set_corrupt_only_decrements_moov_vc_when_was_verified` |
| `test_piece_tracker_regression.py::test_set_corrupt_decrements_when_was_verified` | `set_corrupt_decrements_moov_vc_when_was_verified` |
| `test_piece_tracker_regression.py::test_repeated_corrupt_does_not_go_negative` | `repeated_corrupt_never_underflows_moov_vc` |
| `test_piece_tracker_regression.py::test_set_downloading_decrements_when_clearing_verified` | `set_downloading_decrements_moov_vc_when_clearing_verified` |
| `test_piece_tracker_regression.py::test_overlay_strict_clears_verified_and_updates_moov_vc` | `replace_verified_resets_state_and_updates_moov_vc` |
| Lane segmentation + tie breaking | `lane_segments_matches_expected_buckets_and_tie_break` |
| Multi-threaded safety (`Send + Sync`) | `concurrent_alert_and_query_stress` |

## Deliberate Differences

- Replaced Python's arbitrary-precision `int` bitmaps with fixed `Vec<u64>` word bitsets (`O(num_pieces / 64)` `count_ones`), avoiding heap reallocation on every bit shift.
- `moov_verified_count` uses `saturating_sub(1)` so underflow is structurally impossible even under buggy transitions.
- `PieceStateStore` is pinned `Send + Sync` at compile time and keeps all bitmaps + `moov` counters under a single `Mutex`.
- `SEEK_HOLE` filesystem bootstrap and `libtorrent` handle calls stay in the thin Python adapter (`backend/services/piece_tracker.py`) so `xstream_core` contains zero `unsafe` code.

## Preserved Quirks

- `lane_segments` preserves the exact tie-breaking order (`Verified > Downloading > Corrupt > NotDownloaded` via `>=` against `NotDownloaded`) and 2-decimal percentage rounding.
- `set_verified` / `set_corrupt` / `set_downloading` allow setting any valid torrent piece index (`< num_pieces`), while `on_piece_finished` / `on_hash_failed` clamp to `[start_piece, end_piece]`.
