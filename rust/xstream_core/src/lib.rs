//! Core state machines and native extensions for xstream.
//!
//! This crate houses the incremental Rust port of xstream's latency- and
//! concurrency-sensitive components (see `docs/design/rust-migration.md`).

pub mod extractors;
pub mod filters;
pub mod piece_tracker;
pub mod scoring;

#[cfg(feature = "python")]
mod py_bindings;

pub use extractors::{
    build_magnet, is_hd_source, is_ltx, is_valid_magnet, parse_resolution_tag, parse_sukebei_rss,
    pubdate_to_release, size_to_gb, unescape_magnet, ParseRssError, RssMagnet, RssWork,
};
pub use filters::{hidden_reason, FilterInput, HiddenReason};
pub use piece_tracker::{LaneSegment, PieceLayout, PieceState, PieceStateStore, TrackerError};
pub use scoring::{score_magnet, MagnetMetrics, MagnetSource};
