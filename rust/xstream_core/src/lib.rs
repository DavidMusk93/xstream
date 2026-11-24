//! Core state machines and native extensions for xstream.
//!
//! This crate houses the incremental Rust port of xstream's latency- and
//! concurrency-sensitive components (see `docs/design/rust-migration.md`).

pub mod piece_tracker;

#[cfg(feature = "python")]
mod py_bindings;

pub use piece_tracker::{LaneSegment, PieceLayout, PieceState, PieceStateStore, TrackerError};
