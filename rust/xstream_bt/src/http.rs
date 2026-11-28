//! Axum HTTP router for `BitTorrent` control and HTTP Range video streaming.

use std::{
    io::SeekFrom,
    pin::Pin,
    sync::Arc,
    task::{Context, Poll},
};

use axum::{
    body::Body,
    extract::{Path, Query, State},
    http::{header, HeaderMap, HeaderValue, StatusCode},
    response::{IntoResponse, Response},
    routing::{delete, get, post},
    Json, Router,
};
use serde::{Deserialize, Serialize};
use tokio::io::{AsyncRead, AsyncReadExt, AsyncSeekExt, ReadBuf};
use tokio_util::io::ReaderStream;
use tracing::debug;

use crate::{
    cache::ActiveStreamGuard,
    engine::{
        AddOutcome, BtEngine, CacheListDto, CacheMetricsDto, DeleteFiles, EvictResultDto,
        PauseMode, StartMode, StreamCheckDto, TorrentStatusDto,
    },
    error::BtError,
    range::parse_byte_range,
};

/// Chunk size (64 KiB) used when reading from `librqbit::FileStream`.
const STREAM_BUF_BYTES: usize = 65_536;

/// Maximum bytes returned for an open-ended `Range: bytes=0-` initial request (12 MiB).
///
/// Covers large 4K MP4 `moov` atoms (commonly 8-11 MiB, e.g. MIDA-912's 10.71 MiB moov)
/// plus the first keyframe in a single HTTP round-trip.
const MAX_OPEN_HEAD_RANGE_BYTES: u64 = 12 * 1024 * 1024;

/// Maximum bytes returned for an open-ended `Range: bytes=start-` seek/continuation (4 MiB).
///
/// Smaller 4 MiB chunks complete twice as fast over WAN (~220ms at 18 MB/s) and avoid
/// crossing into the uncached BT frontier when seeking near the end of cached data.
const MAX_OPEN_SEEK_RANGE_BYTES: u64 = 4 * 1024 * 1024;

/// Shared state injected into all HTTP handlers.
#[derive(Debug, Clone)]
pub struct AppState {
    /// Underlying `BitTorrent` engine.
    pub engine: Arc<BtEngine>,
}

/// Build the `axum::Router` for `xstream_bt`.
pub fn build_router(engine: Arc<BtEngine>) -> Router {
    let state = AppState { engine };
    Router::new()
        .route("/health", get(health))
        .route("/torrent/add", post(add_torrent))
        .route("/torrent/status/{hash}", get(torrent_status))
        .route("/torrent/pause", post(pause_torrent))
        .route("/torrent/resume", post(resume_torrent))
        .route("/torrent/seek", post(seek_torrent))
        .route("/torrent/progress", post(progress_torrent))
        .route("/torrent/{hash}", delete(delete_torrent))
        .route("/api/check/{hash}", get(check_stream))
        .route("/api/cache", get(cache_list))
        .route("/api/cache/metrics", get(cache_metrics))
        .route("/api/cache/{hash}", delete(cache_delete))
        .route("/api/cache/pin/{hash}", post(cache_pin).delete(cache_unpin))
        .route("/api/cache/evict", post(cache_evict))
        .route("/stream/{hash}", get(stream_video))
        .with_state(state)
}

async fn cache_list(State(state): State<AppState>) -> Json<CacheListDto> {
    Json(state.engine.cache_list().await)
}

async fn cache_metrics(State(state): State<AppState>) -> Json<CacheMetricsDto> {
    Json(state.engine.cache_metrics().await)
}

#[derive(Serialize)]
struct DeletedResponse {
    deleted: bool,
}

async fn cache_delete(
    State(state): State<AppState>,
    Path(hash): Path<String>,
) -> Result<Json<DeletedResponse>, BtError> {
    state.engine.remove(&hash, DeleteFiles::Remove).await?;
    Ok(Json(DeletedResponse { deleted: true }))
}

async fn cache_pin(
    State(state): State<AppState>,
    Path(hash): Path<String>,
) -> Result<Json<OkResponse>, BtError> {
    state.engine.pin(&hash)?;
    Ok(Json(OkResponse { ok: true }))
}

async fn cache_unpin(
    State(state): State<AppState>,
    Path(hash): Path<String>,
) -> Result<Json<OkResponse>, BtError> {
    state.engine.unpin(&hash)?;
    Ok(Json(OkResponse { ok: true }))
}

async fn cache_evict(State(state): State<AppState>) -> Json<EvictResultDto> {
    Json(state.engine.enforce_quota().await)
}

#[derive(Serialize)]
struct HealthResponse {
    ok: bool,
    engine: &'static str,
    torrents: usize,
}

async fn health(State(state): State<AppState>) -> Json<HealthResponse> {
    Json(HealthResponse {
        ok: true,
        engine: "librqbit",
        torrents: state.engine.torrent_count(),
    })
}

#[derive(Deserialize)]
struct AddTorrentRequest {
    magnet: String,
    #[serde(default)]
    prefetch: bool,
}

async fn add_torrent(
    State(state): State<AppState>,
    Json(req): Json<AddTorrentRequest>,
) -> Result<Json<AddOutcome>, BtError> {
    let mode = if req.prefetch {
        StartMode::Paused
    } else {
        StartMode::Active
    };
    let outcome = state.engine.add_magnet(&req.magnet, mode).await?;
    Ok(Json(outcome))
}

async fn torrent_status(
    State(state): State<AppState>,
    Path(hash): Path<String>,
) -> Result<Json<TorrentStatusDto>, BtError> {
    let st = state.engine.status(&hash)?;
    Ok(Json(st))
}

#[derive(Deserialize)]
struct HashControlRequest {
    hash: String,
}

#[derive(Deserialize)]
struct PauseControlRequest {
    hash: String,
    #[serde(default)]
    force: bool,
}

#[derive(Serialize)]
struct OkResponse {
    ok: bool,
}

async fn pause_torrent(
    State(state): State<AppState>,
    Json(req): Json<PauseControlRequest>,
) -> Result<Json<OkResponse>, BtError> {
    let mode = if req.force {
        PauseMode::Force
    } else {
        PauseMode::RespectPin
    };
    state.engine.pause(&req.hash, mode).await?;
    Ok(Json(OkResponse { ok: true }))
}

async fn resume_torrent(
    State(state): State<AppState>,
    Json(req): Json<HashControlRequest>,
) -> Result<Json<OkResponse>, BtError> {
    state.engine.resume(&req.hash).await?;
    Ok(Json(OkResponse { ok: true }))
}

#[derive(Deserialize)]
struct SeekControlRequest {
    hash: String,
    #[serde(default)]
    time: f64,
    #[serde(default)]
    duration: f64,
}

async fn seek_torrent(
    State(state): State<AppState>,
    Json(req): Json<SeekControlRequest>,
) -> Result<Json<OkResponse>, BtError> {
    state.engine.seek(&req.hash, req.time, req.duration).await?;
    Ok(Json(OkResponse { ok: true }))
}

async fn progress_torrent(
    State(state): State<AppState>,
    Json(req): Json<SeekControlRequest>,
) -> Json<OkResponse> {
    state
        .engine
        .note_playback_progress(&req.hash, req.time, req.duration);
    Json(OkResponse { ok: true })
}

#[derive(Deserialize)]
struct DeleteQuery {
    #[serde(default)]
    delete_files: bool,
}

async fn delete_torrent(
    State(state): State<AppState>,
    Path(hash): Path<String>,
    Query(query): Query<DeleteQuery>,
) -> Result<Json<OkResponse>, BtError> {
    let mode = if query.delete_files {
        DeleteFiles::Remove
    } else {
        DeleteFiles::Keep
    };
    state.engine.remove(&hash, mode).await?;
    Ok(Json(OkResponse { ok: true }))
}

async fn check_stream(
    State(state): State<AppState>,
    Path(hash): Path<String>,
) -> Result<Response, BtError> {
    let dto: StreamCheckDto = state.engine.check(&hash)?;
    let mut res = Json(dto).into_response();
    res.headers_mut().insert(
        header::CACHE_CONTROL,
        HeaderValue::from_static("no-store, no-cache, must-revalidate, max-age=0"),
    );
    Ok(res)
}

struct GuardedReader {
    inner: Box<dyn AsyncRead + Send + Unpin>,
    _guard: ActiveStreamGuard,
}

impl AsyncRead for GuardedReader {
    fn poll_read(
        mut self: Pin<&mut Self>,
        cx: &mut Context<'_>,
        buf: &mut ReadBuf<'_>,
    ) -> Poll<std::io::Result<()>> {
        Pin::new(&mut *self.inner).poll_read(cx, buf)
    }
}

async fn stream_video(
    State(state): State<AppState>,
    Path(hash): Path<String>,
    req_headers: HeaderMap,
) -> Result<Response, BtError> {
    let opened = state.engine.open_stream(&hash).await?;
    let total_size = opened.total_size;
    let mime = opened.mime;
    let guard = opened.guard;
    let mut stream = opened.stream;

    let range_header = req_headers.get(header::RANGE).and_then(|v| v.to_str().ok());

    debug!(hash = %hash, total_size, range = ?range_header, "streaming video");

    let mut out_headers = HeaderMap::new();
    out_headers.insert(header::ACCEPT_RANGES, HeaderValue::from_static("bytes"));
    out_headers.insert(header::CONTENT_TYPE, HeaderValue::from_static(mime));

    let (status, reader): (StatusCode, Box<dyn AsyncRead + Send + Unpin>) =
        if let Some(raw_range) = range_header {
            let Some(mut range) = parse_byte_range(raw_range, total_size) else {
                return Err(BtError::InvalidRange { total_size, mime });
            };
            let is_open_ended = raw_range.trim().ends_with('-');
            if is_open_ended {
                let cap = if range.start == 0 {
                    MAX_OPEN_HEAD_RANGE_BYTES
                } else {
                    MAX_OPEN_SEEK_RANGE_BYTES
                };
                let capped_end = range.start.saturating_add(cap - 1).min(total_size - 1);
                if capped_end < range.end {
                    range.end = capped_end;
                }
            }

            stream
                .seek(SeekFrom::Start(range.start))
                .await
                .map_err(|err| BtError::Internal(format!("stream seek failed: {err}")))?;

            state.engine.note_stream_offset(&hash, range.start).await;

            let len = range.len();
            if let Ok(val) = HeaderValue::from_str(&len.to_string()) {
                out_headers.insert(header::CONTENT_LENGTH, val);
            }
            if let Ok(val) =
                HeaderValue::from_str(&format!("bytes {}-{}/{total_size}", range.start, range.end))
            {
                out_headers.insert(header::CONTENT_RANGE, val);
            }

            (StatusCode::PARTIAL_CONTENT, Box::new(stream.take(len)))
        } else {
            if let Ok(val) = HeaderValue::from_str(&total_size.to_string()) {
                out_headers.insert(header::CONTENT_LENGTH, val);
            }
            (StatusCode::OK, Box::new(stream))
        };

    let guarded = GuardedReader {
        inner: reader,
        _guard: guard,
    };
    let body_stream = ReaderStream::with_capacity(guarded, STREAM_BUF_BYTES);
    Ok((status, out_headers, Body::from_stream(body_stream)).into_response())
}
