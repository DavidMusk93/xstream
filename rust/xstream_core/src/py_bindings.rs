//! Thin `PyO3` bindings exposing [`PieceStateStore`] to Python.

use std::collections::HashMap;
use std::path::Path;

use pyo3::exceptions::PyValueError;
use pyo3::prelude::*;

use crate::covers;
use crate::event_bus::{EventBus, SubscriberId};
use crate::extractors;
use crate::filters::{self, FilterInput};
use crate::piece_tracker::{PieceLayout, PieceStateStore};
use crate::scoring::{self, MagnetMetrics, MagnetSource};

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

/// Returns the hidden-reason tag for a title, or `None` to keep it.
#[pyfunction]
#[expect(
    clippy::needless_pass_by_value,
    reason = "PyO3 FromPyObject extracts Python lists into owned Vec<String>"
)]
fn py_hidden_reason(
    code: &str,
    title: &str,
    star_count: usize,
    magnet_resolutions: Vec<String>,
    own_names: Vec<String>,
    roster_names: Vec<String>,
) -> Option<&'static str> {
    let res_refs: Vec<&str> = magnet_resolutions.iter().map(String::as_str).collect();
    let own_refs: Vec<&str> = own_names.iter().map(String::as_str).collect();
    let roster_refs: Vec<&str> = roster_names.iter().map(String::as_str).collect();
    let input = FilterInput {
        code,
        title,
        star_count,
        magnet_resolutions: &res_refs,
    };
    filters::hidden_reason(&input, &own_refs, &roster_refs).map(filters::HiddenReason::as_str)
}

/// Computes the deterministic ranking score for a magnet candidate.
#[pyfunction]
#[expect(
    clippy::fn_params_excessive_bools,
    reason = "PyO3 boundary matches Python MagnetCandidate.is_hhd800 boolean attribute"
)]
fn py_score_magnet(resolution: &str, size: &str, seed: i64, is_hhd800: bool) -> f64 {
    let source = if is_hhd800 {
        MagnetSource::Hhd800
    } else {
        MagnetSource::Standard
    };
    let metrics = MagnetMetrics {
        resolution,
        size,
        seed,
        source,
    };
    scoring::score_magnet(&metrics)
}

/// HTML-unescapes a magnet URI (up to 3 passes for double-escaped sources).
#[pyfunction]
fn py_unescape_magnet(magnet_url: &str) -> String {
    extractors::unescape_magnet(magnet_url)
}

/// Validates a v1 `btih` magnet URI with a 40-hex hash and no leftover `&amp;`.
#[pyfunction]
fn py_is_valid_magnet(magnet_url: &str) -> bool {
    extractors::is_valid_magnet(magnet_url)
}

/// Returns `true` if the magnet `dn` or torrent title is an LTX release.
#[pyfunction]
fn py_is_ltx(text: &str) -> bool {
    extractors::is_ltx(text)
}

/// Returns `true` if a row or title comes from a curated HD release group.
#[pyfunction]
fn py_is_hd_source(raw_text: &str, dn_or_title: &str) -> bool {
    extractors::is_hd_source(raw_text, dn_or_title)
}

/// Maps resolution hints in a torrent title to the standard vocabulary.
#[pyfunction]
fn py_parse_resolution_tag(title: &str) -> &'static str {
    extractors::parse_resolution_tag(title)
}

/// Converts nyaa size strings like `"3.6 GiB"` to `"3.6GB"`.
#[pyfunction]
fn py_size_to_gb(size: &str) -> String {
    extractors::size_to_gb(size)
}

/// Python-visible representation of one grouped work from Sukebei RSS.
type PyRssMagnetTuple = (String, String, String, i64, i64, bool);
type PyRssWorkTuple = (
    String,
    String,
    Option<String>,
    Option<i64>,
    Vec<PyRssMagnetTuple>,
);

/// Parses a Sukebei RSS XML document into grouped work tuples.
#[pyfunction]
#[expect(
    clippy::needless_pass_by_value,
    reason = "PyO3 FromPyObject extracts Python lists into owned Vec<String>"
)]
fn py_parse_sukebei_rss(rss_xml: &str, star_names: Vec<String>) -> PyResult<Vec<PyRssWorkTuple>> {
    let refs: Vec<&str> = star_names.iter().map(String::as_str).collect();
    let works = extractors::parse_sukebei_rss(rss_xml, &refs)
        .map_err(|err| PyValueError::new_err(err.to_string()))?;
    Ok(works
        .into_iter()
        .map(|w| {
            let mags = w
                .magnets
                .into_iter()
                .map(|m| (m.magnet, m.resolution, m.size, m.seed, m.leech, m.is_hhd800))
                .collect();
            (w.code, w.title, w.release_date, w.likes, mags)
        })
        .collect())
}

/// Python-visible wrapper around [`EventBus`].
#[pyclass(name = "EventBus")]
#[derive(Debug)]
struct PyEventBus {
    inner: EventBus,
}

#[pymethods]
impl PyEventBus {
    #[new]
    #[pyo3(signature = (capacity = 256))]
    fn new(capacity: usize) -> Self {
        Self {
            inner: EventBus::with_capacity(capacity),
        }
    }

    fn subscribe(&self) -> u64 {
        self.inner.subscribe().as_u64()
    }

    fn unsubscribe(&self, sub_id: u64) -> bool {
        self.inner.unsubscribe(SubscriberId::from_u64(sub_id))
    }

    fn subscriber_count(&self) -> usize {
        self.inner.subscriber_count()
    }

    fn publish(&self, payload: &str, resync_marker: &str) -> (Vec<u64>, Vec<(u64, usize)>) {
        let report = self.inner.publish(payload, resync_marker);
        let notified = report
            .notified
            .into_iter()
            .map(SubscriberId::as_u64)
            .collect();
        let coalesced = report
            .coalesced
            .into_iter()
            .map(|(id, dropped)| (id.as_u64(), dropped))
            .collect();
        (notified, coalesced)
    }

    fn try_recv(&self, sub_id: u64) -> Option<String> {
        self.inner.try_recv(SubscriberId::from_u64(sub_id))
    }

    fn drain(&self, sub_id: u64) -> Vec<String> {
        self.inner.drain(SubscriberId::from_u64(sub_id))
    }
}

/// Scans `titles_dir` and returns `{UPPER_CODE: (has_full, has_thumb, has_mid)}`.
#[pyfunction]
fn py_scan_cover_files(titles_dir: &str) -> HashMap<String, (bool, bool, bool)> {
    covers::scan_cover_files(Path::new(titles_dir))
        .into_iter()
        .map(|(code, p)| (code, (p.has_full, p.has_thumb, p.has_mid)))
        .collect()
}

/// Native Rust extension module for xstream.
#[pymodule]
fn xstream_core(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_class::<PyPieceStateStore>()?;
    m.add_class::<PyEventBus>()?;
    m.add_function(wrap_pyfunction!(py_hidden_reason, m)?)?;
    m.add_function(wrap_pyfunction!(py_score_magnet, m)?)?;
    m.add_function(wrap_pyfunction!(py_unescape_magnet, m)?)?;
    m.add_function(wrap_pyfunction!(py_is_valid_magnet, m)?)?;
    m.add_function(wrap_pyfunction!(py_is_ltx, m)?)?;
    m.add_function(wrap_pyfunction!(py_is_hd_source, m)?)?;
    m.add_function(wrap_pyfunction!(py_parse_resolution_tag, m)?)?;
    m.add_function(wrap_pyfunction!(py_size_to_gb, m)?)?;
    m.add_function(wrap_pyfunction!(py_parse_sukebei_rss, m)?)?;
    m.add_function(wrap_pyfunction!(py_scan_cover_files, m)?)?;
    Ok(())
}
