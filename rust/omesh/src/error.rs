//! Error types and HTTP error responses for `omesh`.

use std::fmt;

use axum::{
    http::StatusCode,
    response::{IntoResponse, Response},
    Json,
};
use serde::Serialize;

/// Domain error for `omesh` HTTP handlers and background jobs.
#[derive(Debug)]
#[non_exhaustive]
pub enum MeshError {
    /// Malformed request parameter or info-hash.
    InvalidInput(String),
    /// Missing or invalid Bearer authentication token.
    Unauthorized,
    /// Requested media hash or job ID was not found.
    NotFound(String),
    /// Upstream `ostore`, peer `omesh`, or `xstream_bt` failure.
    Upstream(String),
    /// Internal runtime or I/O error.
    Internal(String),
}

impl fmt::Display for MeshError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::InvalidInput(msg) => write!(f, "invalid input: {msg}"),
            Self::Unauthorized => f.write_str("unauthorized"),
            Self::NotFound(msg) => write!(f, "not found: {msg}"),
            Self::Upstream(msg) => write!(f, "upstream error: {msg}"),
            Self::Internal(msg) => write!(f, "internal error: {msg}"),
        }
    }
}

impl std::error::Error for MeshError {}

#[derive(Serialize)]
struct ErrorBody {
    detail: String,
}

impl IntoResponse for MeshError {
    fn into_response(self) -> Response {
        let (status, detail) = match self {
            Self::InvalidInput(msg) => (StatusCode::BAD_REQUEST, msg),
            Self::Unauthorized => (StatusCode::UNAUTHORIZED, "unauthorized".to_string()),
            Self::NotFound(msg) => (StatusCode::NOT_FOUND, msg),
            Self::Upstream(msg) => (StatusCode::BAD_GATEWAY, msg),
            Self::Internal(msg) => (StatusCode::INTERNAL_SERVER_ERROR, msg),
        };
        (status, Json(ErrorBody { detail })).into_response()
    }
}
