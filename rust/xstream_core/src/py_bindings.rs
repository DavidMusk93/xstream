//! Thin `PyO3` bindings exposing [`PieceStateStore`] to Python.

use pyo3::exceptions::PyValueError;
use pyo3::prelude::*;

use crate::piece_tracker::{PieceLayout, PieceStateStore};

/// Python-visible wrapper around [`PieceStateStore`].
#[pyclass(name = "PieceStateStore")]
#[derive(Debug)]
struct PyPieceStateStore {
    inner: PieceStateStore,
}

#[pymethods]
impl PyPieceStateStore {
    #[new]
    fn new(
        num_pieces: usize,
        piece_length: u64,
        file_offset: u64,
        video_size: u64,
    ) -> PyResult<Self> {
        let layout = PieceLayout {
            num_pieces,
            piece_length,
            file_offset,
            video_size,
        };
        let inner = PieceStateStore::try_new(layout)
            .map_err(|err| PyValueError::new_err(err.to_string()))?;
        Ok(Self { inner })
    }

    #[getter]
    fn start_piece(&self) -> usize {
        self.inner.start_piece()
    }

    #[getter]
    fn end_piece(&self) -> usize {
        self.inner.end_piece()
    }

    #[getter]
    fn moov_verified_count(&self) -> usize {
        self.inner.moov_verified_count()
    }

    fn set_moov_range(&self, moov_start: u64, moov_end: u64) {
        self.inner.set_moov_range(moov_start, moov_end);
    }

    fn set_head_tail_counts(&self, head_count: usize, tail_count: usize) {
        self.inner.set_head_tail_counts(head_count, tail_count);
    }

    fn replace_verified_pieces(&self, pieces: Vec<usize>) {
        self.inner.replace_verified_pieces(pieces);
    }

    fn set_verified(&self, piece: usize) {
        self.inner.set_verified(piece);
    }

    fn set_corrupt(&self, piece: usize) {
        self.inner.set_corrupt(piece);
    }

    fn set_downloading(&self, piece: usize) {
        self.inner.set_downloading(piece);
    }

    fn on_piece_finished(&self, piece: usize) -> bool {
        self.inner.on_piece_finished(piece)
    }

    fn on_hash_failed(&self, piece: usize) -> bool {
        self.inner.on_hash_failed(piece)
    }

    fn is_verified(&self, piece: usize) -> bool {
        self.inner.is_verified(piece)
    }

    fn piece_state(&self, piece: usize) -> u8 {
        self.inner.piece_state(piece).as_u8()
    }

    fn verified_count(&self) -> usize {
        self.inner.verified_count()
    }

    fn head_ready(&self) -> bool {
        self.inner.head_ready()
    }

    fn claim_pieces_for_download(&self, start_piece: usize, end_piece: usize) -> Vec<usize> {
        self.inner.claim_pieces_for_download(start_piece, end_piece)
    }

    fn clear_downloading(&self) {
        self.inner.clear_downloading();
    }

    fn lane_segments(&self, segments: usize) -> Vec<(f64, f64, u8)> {
        self.inner
            .lane_segments(segments)
            .into_iter()
            .map(|seg| (seg.start_pct, seg.end_pct, seg.state.as_u8()))
            .collect()
    }
}

/// Native Rust extension module for xstream.
#[pymodule]
fn xstream_core(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_class::<PyPieceStateStore>()?;
    Ok(())
}
