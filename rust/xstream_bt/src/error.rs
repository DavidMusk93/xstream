//! Error types and HTTP status mapping for `xstream_bt`.

use std::fmt;

use axum::{
    http::{header, HeaderValue, StatusCode},
    response::{IntoResponse, Response},
    Json,
};
use serde::Serialize;

/// Errors produced by the `BitTorrent` engine and HTTP streaming layer.
#[derive(Debug)]
#[non_exhaustive]
pub enum BtError {
    /// Caller supplied an invalid info-hash or magnet URI.
    InvalidInput(String),
    /// Requested torrent hash is not managed by the engine.
    NotFound(String),
    /// Torrent is managed but metadata or video file is not yet available.
    NotReady(String),
    /// Requested HTTP `Range` header is malformed or out of bounds.
    InvalidRange {
        /// Total length of the target video file in bytes.
        total_size: u64,
        /// MIME type of the target video file.
        mime: &'static str,
    },
    /// Internal engine or I/O failure.
    Internal(String),
}

impl fmt::Display for BtError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::InvalidInput(msg) => write!(f, "invalid input: {msg}"),
            Self::NotFound(hash) => write!(f, "torrent not found: {hash}"),
            Self::NotReady(msg) => write!(f, "torrent not ready: {msg}"),
            Self::InvalidRange { total_size, .. } => {
                write!(f, "invalid byte range for file of size {total_size}")
            }
            Self::Internal(msg) => write!(f, "internal engine error: {msg}"),
        }
    }
}

impl std::error::Error for BtError {}

#[derive(Serialize)]
struct ErrorBody {
    detail: String,
}

impl IntoResponse for BtError {
    fn into_response(self) -> Response {
        match self {
            Self::InvalidInput(detail) => {
                (StatusCode::BAD_REQUEST, Json(ErrorBody { detail })).into_response()
            }
            Self::NotFound(hash) => (
                StatusCode::NOT_FOUND,
                Json(ErrorBody {
                    detail: format!("Torrent not found: {hash}"),
                }),
            )
                .into_response(),
            Self::NotReady(detail) => {
                (StatusCode::SERVICE_UNAVAILABLE, Json(ErrorBody { detail })).into_response()
            }
            Self::InvalidRange { total_size, mime } => {
                let mut res = (StatusCode::RANGE_NOT_SATISFIABLE, "").into_response();
                let headers = res.headers_mut();
                if let Ok(val) = HeaderValue::from_str(&format!("bytes */{total_size}")) {
                    headers.insert(header::CONTENT_RANGE, val);
                }
                headers.insert(header::ACCEPT_RANGES, HeaderValue::from_static("bytes"));
                headers.insert(header::CONTENT_TYPE, HeaderValue::from_static(mime));
                res
            }
            Self::Internal(detail) => (
                StatusCode::INTERNAL_SERVER_ERROR,
                Json(ErrorBody { detail }),
            )
                .into_response(),
        }
    }
}
