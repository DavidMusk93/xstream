//! Core state machines and native extensions for xstream.
//!
//! This crate houses the incremental Rust port of xstream's latency- and
//! concurrency-sensitive components (see `docs/design/rust-migration.md`).

pub mod filters;
pub mod piece_tracker;
pub mod scoring;

#[cfg(feature = "python")]
mod py_bindings;

pub use filters::{hidden_reason, FilterInput, HiddenReason};
pub use piece_tracker::{LaneSegment, PieceLayout, PieceState, PieceStateStore, TrackerError};
pub use scoring::{score_magnet, MagnetMetrics, MagnetSource};
