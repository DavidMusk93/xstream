//! Axum HTTP router for `BitTorrent` control and HTTP Range video streaming.

use std::{io::SeekFrom, sync::Arc};

use axum::{
    body::Body,
    extract::{Path, Query, State},
    http::{header, HeaderMap, HeaderValue, StatusCode},
    response::{IntoResponse, Response},
    routing::{delete, get, post},
    Json, Router,
};
use serde::{Deserialize, Serialize};
use tokio::io::{AsyncRead, AsyncReadExt, AsyncSeekExt};
use tokio_util::io::ReaderStream;
use tracing::debug;

use crate::{
    engine::{AddOutcome, BtEngine, DeleteFiles, StartMode, StreamCheckDto, TorrentStatusDto},
    error::BtError,
    range::parse_byte_range,
};

/// Chunk size (64 KiB) used when reading from `librqbit::FileStream`.
const STREAM_BUF_BYTES: usize = 65_536;

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
        .route("/torrent/seek", post(seek_noop))
        .route("/torrent/progress", post(progress_noop))
        .route("/torrent/{hash}", delete(delete_torrent))
        .route("/api/check/{hash}", get(check_stream))
        .route("/stream/{hash}", get(stream_video))
        .with_state(state)
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

#[derive(Serialize)]
struct OkResponse {
    ok: bool,
}

async fn pause_torrent(
    State(state): State<AppState>,
    Json(req): Json<HashControlRequest>,
) -> Result<Json<OkResponse>, BtError> {
    state.engine.pause(&req.hash).await?;
    Ok(Json(OkResponse { ok: true }))
}

async fn resume_torrent(
    State(state): State<AppState>,
    Json(req): Json<HashControlRequest>,
) -> Result<Json<OkResponse>, BtError> {
    state.engine.resume(&req.hash).await?;
    Ok(Json(OkResponse { ok: true }))
}

async fn seek_noop(Json(_req): Json<HashControlRequest>) -> Json<OkResponse> {
    // librqbit FileStream handles seek prioritization natively via HTTP Range requests.
    Json(OkResponse { ok: true })
}

async fn progress_noop(Json(_req): Json<HashControlRequest>) -> Json<OkResponse> {
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

async fn stream_video(
    State(state): State<AppState>,
    Path(hash): Path<String>,
    req_headers: HeaderMap,
) -> Result<Response, BtError> {
    let opened = state.engine.open_stream(&hash).await?;
    let total_size = opened.total_size;
    let mime = opened.mime;
    let mut stream = opened.stream;

    let range_header = req_headers.get(header::RANGE).and_then(|v| v.to_str().ok());

    debug!(hash = %hash, total_size, range = ?range_header, "streaming video");

    let mut out_headers = HeaderMap::new();
    out_headers.insert(header::ACCEPT_RANGES, HeaderValue::from_static("bytes"));
    out_headers.insert(header::CONTENT_TYPE, HeaderValue::from_static(mime));

    let (status, reader): (StatusCode, Box<dyn AsyncRead + Send + Unpin>) =
        if let Some(raw_range) = range_header {
            let Some(range) = parse_byte_range(raw_range, total_size) else {
                return Err(BtError::InvalidRange { total_size, mime });
            };

            stream
                .seek(SeekFrom::Start(range.start))
                .await
                .map_err(|err| BtError::Internal(format!("stream seek failed: {err}")))?;

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

    let body_stream = ReaderStream::with_capacity(reader, STREAM_BUF_BYTES);
    Ok((status, out_headers, Body::from_stream(body_stream)).into_response())
}
