//! Axum HTTP router for `omesh` HTTP Range CDN streaming, peer probing, and compute jobs.

use std::{path::Path, sync::Arc, time::Duration};

use axum::{
    body::Body,
    extract::{Path as AxumPath, State},
    http::{header, HeaderMap, HeaderValue, StatusCode},
    response::{IntoResponse, Response},
    routing::get,
    Json, Router,
};
use reqwest::Client;
use serde::{Deserialize, Serialize};
use tracing::debug;

use crate::{
    config::{normalize_hash, Config},
    error::MeshError,
    jobs::{JobManager, JobRecord, JobSpec},
    peer::{NodeHealth, PeerRegistry, PeerSnapshot},
};

/// Shared application state for all `omesh` handlers.
#[derive(Debug, Clone)]
pub struct AppState {
    /// Runtime configuration.
    pub config: Arc<Config>,
    /// Shared HTTP client for `ostore`, peers, and `xstream_bt`.
    pub client: Client,
    /// Live peer registry.
    pub peers: PeerRegistry,
    /// Compute job manager.
    pub jobs: JobManager,
}

/// Response payload matching xstream's `/api/check/{hash}` contract plus CDN source attribution.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct StreamCheckDto {
    /// Lowercase 40-char hex info-hash.
    pub hash: String,
    /// True if cached in `ostore`, a peer edge node, or local `xstream_bt`.
    pub cached: bool,
    /// True when ready to stream immediately via `GET /stream/{hash}`.
    pub head_ready: bool,
    /// Relative path or object key.
    pub path: String,
    /// Total file size in bytes.
    pub size: u64,
    /// MIME type string.
    pub mime: String,
    /// Origin tier that will serve this stream (`"ostore"`, `"peer:<id>"`, `"local-bt"`, `"miss"`).
    #[serde(default)]
    pub source: String,
}

/// Build the `axum::Router` for `omesh`.
pub fn build_router(state: AppState) -> Router {
    Router::new()
        .route("/health", get(health))
        .route("/mesh/nodes", get(list_nodes))
        .route("/mesh/probe/{hash}", get(probe_local))
        .route("/mesh/jobs", get(list_jobs).post(submit_job))
        .route("/mesh/jobs/{id}", get(get_job))
        .route("/api/check/{hash}", get(check_stream))
        .route("/stream/{hash}", get(stream_video))
        .with_state(state)
}

fn require_token(config: &Config, headers: &HeaderMap) -> Result<(), MeshError> {
    let Some(expected) = config.token.as_deref() else {
        return Ok(());
    };
    let provided = headers
        .get(header::AUTHORIZATION)
        .and_then(|v| v.to_str().ok())
        .and_then(|s| s.strip_prefix("Bearer "))
        .map(str::trim);
    if provided == Some(expected) {
        Ok(())
    } else {
        Err(MeshError::Unauthorized)
    }
}

async fn health(State(state): State<AppState>) -> Json<NodeHealth> {
    let free_disk_bytes = free_disk_for_path(&state.config.work_dir);
    Json(NodeHealth {
        ok: true,
        node_id: state.config.node_id.clone(),
        bt_enabled: state.config.bt_url.is_some(),
        ostore_enabled: state.config.ostore_url.is_some(),
        active_jobs: state.jobs.active_count(),
        free_disk_bytes,
    })
}

#[derive(Serialize)]
struct NodesResponse {
    node_id: String,
    peers: Vec<PeerSnapshot>,
}

async fn list_nodes(
    State(state): State<AppState>,
    headers: HeaderMap,
) -> Result<Json<NodesResponse>, MeshError> {
    require_token(&state.config, &headers)?;
    Ok(Json(NodesResponse {
        node_id: state.config.node_id.clone(),
        peers: state.peers.list(),
    }))
}

async fn list_jobs(
    State(state): State<AppState>,
    headers: HeaderMap,
) -> Result<Json<Vec<JobRecord>>, MeshError> {
    require_token(&state.config, &headers)?;
    Ok(Json(state.jobs.list()))
}

async fn get_job(
    State(state): State<AppState>,
    headers: HeaderMap,
    AxumPath(id): AxumPath<String>,
) -> Result<Json<JobRecord>, MeshError> {
    require_token(&state.config, &headers)?;
    state
        .jobs
        .get(&id)
        .map(Json)
        .ok_or_else(|| MeshError::NotFound(format!("job {id} not found")))
}

async fn submit_job(
    State(state): State<AppState>,
    headers: HeaderMap,
    Json(spec): Json<JobSpec>,
) -> Result<Json<JobRecord>, MeshError> {
    require_token(&state.config, &headers)?;
    let rec = state.jobs.submit(spec).await?;
    Ok(Json(rec))
}

/// Local-only probe called by remote peers to avoid multi-hop proxy loops.
async fn probe_local(
    State(state): State<AppState>,
    headers: HeaderMap,
    AxumPath(raw_hash): AxumPath<String>,
) -> Result<Json<StreamCheckDto>, MeshError> {
    require_token(&state.config, &headers)?;
    let hash = normalize_hash(&raw_hash)
        .ok_or_else(|| MeshError::InvalidInput("invalid info-hash".to_string()))?;

    if let Some(hit) = probe_ostore(&state, &hash).await {
        return Ok(Json(hit));
    }
    if let Some(hit) = probe_local_bt(&state, &hash).await {
        return Ok(Json(hit));
    }
    Ok(Json(empty_check(hash)))
}

async fn check_stream(
    State(state): State<AppState>,
    headers: HeaderMap,
    AxumPath(raw_hash): AxumPath<String>,
) -> Result<Response, MeshError> {
    let hash = normalize_hash(&raw_hash)
        .ok_or_else(|| MeshError::InvalidInput("invalid info-hash".to_string()))?;
    let is_hop = headers.contains_key("x-omesh-hop");

    // L1/L3: ostore HTTP CDN (archived fast-start MP4).
    if let Some(hit) = probe_ostore(&state, &hash).await {
        return Ok(no_store_json(hit));
    }

    // L2: healthy 1-2ms peer edge nodes (single hop only).
    if !is_hop {
        if let Some(hit) = probe_peers(&state, &hash).await {
            return Ok(no_store_json(hit));
        }
    }

    // L4: local xstream_bt fallback.
    if let Some(hit) = probe_local_bt(&state, &hash).await {
        return Ok(no_store_json(hit));
    }

    Ok(no_store_json(empty_check(hash)))
}

async fn stream_video(
    State(state): State<AppState>,
    headers: HeaderMap,
    AxumPath(raw_hash): AxumPath<String>,
) -> Result<Response, MeshError> {
    let hash = normalize_hash(&raw_hash)
        .ok_or_else(|| MeshError::InvalidInput("invalid info-hash".to_string()))?;
    let range_hdr = headers.get(header::RANGE).and_then(|v| v.to_str().ok());
    let is_hop = headers.contains_key("x-omesh-hop");

    // 1. Try ostore CDN directly (30+ MB/s HTTP Range, zero BT overhead).
    if let Some(ostore_url) = state.config.ostore_url.as_deref() {
        let key = format!("{}/{hash}.mp4", state.config.media_prefix);
        let url = format!("{ostore_url}/api/files/{key}");
        let mut req = state.client.get(&url);
        if let Some(tok) = &state.config.ostore_token {
            req = req.bearer_auth(tok);
        }
        if let Some(r) = range_hdr {
            req = req.header(header::RANGE, r);
        }
        if let Ok(resp) = req.send().await {
            if resp.status().is_success() || resp.status() == StatusCode::PARTIAL_CONTENT {
                debug!(hash = %hash, "serving stream from ostore CDN");
                return Ok(proxy_stream_response(resp, "ostore"));
            }
        }
    }

    // 2. Try healthy 1-2ms peer edge nodes that report head_ready.
    if !is_hop {
        if let Some((peer_id, peer_url)) = find_ready_peer(&state, &hash).await {
            let url = format!("{peer_url}/stream/{hash}");
            let mut req = state.client.get(&url).header("x-omesh-hop", "1");
            if let Some(tok) = &state.config.token {
                req = req.bearer_auth(tok);
            }
            if let Some(r) = range_hdr {
                req = req.header(header::RANGE, r);
            }
            if let Ok(resp) = req.send().await {
                if resp.status().is_success() || resp.status() == StatusCode::PARTIAL_CONTENT {
                    debug!(hash = %hash, peer = %peer_id, "serving stream from peer edge");
                    return Ok(proxy_stream_response(resp, &format!("peer:{peer_id}")));
                }
            }
        }
    }

    // 3. Fallback to local xstream_bt.
    let bt_url = state
        .config
        .bt_url
        .as_deref()
        .ok_or_else(|| MeshError::NotFound(format!("media {hash} not found in mesh")))?;
    let mut req = state.client.get(format!("{bt_url}/stream/{hash}"));
    if let Some(r) = range_hdr {
        req = req.header(header::RANGE, r);
    }
    let resp = req
        .send()
        .await
        .map_err(|err| MeshError::Upstream(format!("local xstream_bt stream failed: {err}")))?;
    Ok(proxy_stream_response(resp, "local-bt"))
}

fn proxy_stream_response(upstream: reqwest::Response, source: &str) -> Response {
    let status =
        StatusCode::from_u16(upstream.status().as_u16()).unwrap_or(StatusCode::BAD_GATEWAY);
    let mut out_headers = HeaderMap::new();
    for key in [
        header::CONTENT_TYPE,
        header::CONTENT_LENGTH,
        header::CONTENT_RANGE,
        header::ACCEPT_RANGES,
        header::ETAG,
    ] {
        if let Some(val) = upstream.headers().get(&key) {
            if let Ok(hv) = HeaderValue::from_bytes(val.as_bytes()) {
                out_headers.insert(key, hv);
            }
        }
    }
    if let Ok(hv) = HeaderValue::from_str(source) {
        out_headers.insert("x-omesh-source", hv);
    }
    let body = Body::from_stream(upstream.bytes_stream());
    (status, out_headers, body).into_response()
}

fn no_store_json(dto: StreamCheckDto) -> Response {
    let mut res = Json(dto).into_response();
    res.headers_mut().insert(
        header::CACHE_CONTROL,
        HeaderValue::from_static("no-store, no-cache, must-revalidate, max-age=0"),
    );
    res
}

fn empty_check(hash: String) -> StreamCheckDto {
    StreamCheckDto {
        hash,
        cached: false,
        head_ready: false,
        path: String::new(),
        size: 0,
        mime: "video/mp4".to_string(),
        source: "miss".to_string(),
    }
}

async fn probe_ostore(state: &AppState, hash: &str) -> Option<StreamCheckDto> {
    let ostore_url = state.config.ostore_url.as_deref()?;
    let key = format!("{}/{hash}.mp4", state.config.media_prefix);
    let url = format!("{ostore_url}/api/files/{key}");
    let mut req = state.client.head(&url).timeout(Duration::from_millis(800));
    if let Some(tok) = &state.config.ostore_token {
        req = req.bearer_auth(tok);
    }
    let resp = req.send().await.ok()?;
    if !resp.status().is_success() {
        return None;
    }
    let size = resp
        .headers()
        .get(header::CONTENT_LENGTH)
        .and_then(|v| v.to_str().ok())
        .and_then(|s| s.parse::<u64>().ok())
        .unwrap_or(0);
    if size == 0 {
        return None;
    }
    Some(StreamCheckDto {
        hash: hash.to_string(),
        cached: true,
        head_ready: true,
        path: key,
        size,
        mime: "video/mp4".to_string(),
        source: "ostore".to_string(),
    })
}

async fn probe_local_bt(state: &AppState, hash: &str) -> Option<StreamCheckDto> {
    let bt_url = state.config.bt_url.as_deref()?;
    let resp = state
        .client
        .get(format!("{bt_url}/api/check/{hash}"))
        .timeout(Duration::from_secs(2))
        .send()
        .await
        .ok()?;
    if !resp.status().is_success() {
        return None;
    }
    let mut dto = resp.json::<StreamCheckDto>().await.ok()?;
    dto.source = "local-bt".to_string();
    Some(dto)
}

async fn probe_peers(state: &AppState, hash: &str) -> Option<StreamCheckDto> {
    for peer in state.peers.healthy_peers() {
        let url = format!("{}/mesh/probe/{hash}", peer.url);
        let mut req = state.client.get(&url).timeout(Duration::from_millis(500));
        if let Some(tok) = &state.config.token {
            req = req.bearer_auth(tok);
        }
        if let Ok(resp) = req.send().await {
            if resp.status().is_success() {
                if let Ok(mut dto) = resp.json::<StreamCheckDto>().await {
                    if dto.head_ready {
                        dto.source = format!("peer:{}", peer.id);
                        return Some(dto);
                    }
                }
            }
        }
    }
    None
}

async fn find_ready_peer(state: &AppState, hash: &str) -> Option<(String, String)> {
    for peer in state.peers.healthy_peers() {
        let url = format!("{}/mesh/probe/{hash}", peer.url);
        let mut req = state.client.get(&url).timeout(Duration::from_millis(400));
        if let Some(tok) = &state.config.token {
            req = req.bearer_auth(tok);
        }
        if let Ok(resp) = req.send().await {
            if resp.status().is_success() {
                if let Ok(dto) = resp.json::<StreamCheckDto>().await {
                    if dto.head_ready {
                        return Some((peer.id, peer.url));
                    }
                }
            }
        }
    }
    None
}

fn free_disk_for_path(path: &Path) -> u64 {
    let probe = if path.exists() { path } else { Path::new("/") };
    let output = std::process::Command::new("df")
        .arg("-B1")
        .arg("--output=avail")
        .arg(probe)
        .output();
    let Ok(out) = output else {
        return 0;
    };
    if !out.status.success() {
        return 0;
    }
    String::from_utf8_lossy(&out.stdout)
        .lines()
        .nth(1)
        .and_then(|line| line.trim().parse::<u64>().ok())
        .unwrap_or(0)
}
