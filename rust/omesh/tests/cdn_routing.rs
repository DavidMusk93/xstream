//! End-to-end HTTP Range CDN routing and auth tests for `omesh`.

use std::{path::PathBuf, sync::Arc};

use axum::{
    http::{header, StatusCode},
    routing::{get, head},
    Json, Router,
};
use omesh::{
    config::{Config, PeerSpec},
    jobs::JobManager,
    peer::PeerRegistry,
    router::{build_router, AppState, StreamCheckDto},
};
use reqwest::Client;
use tokio::net::TcpListener;

async fn spawn_server(app: Router) -> String {
    let listener = TcpListener::bind("127.0.0.1:0")
        .await
        .expect("bind ephemeral port");
    let addr = listener.local_addr().expect("read local addr");
    tokio::spawn(async move {
        let _ = axum::serve(listener, app).await;
    });
    format!("http://{addr}")
}

async fn spawn_mock_mesh(hash: &str) -> String {
    let expected_key = format!("/api/files/xstream/media/{hash}.mp4");
    let ostore_app = Router::new().route(
        &expected_key,
        head(|| async {
            (
                StatusCode::OK,
                [
                    (header::CONTENT_LENGTH, "16"),
                    (header::CONTENT_TYPE, "video/mp4"),
                ],
            )
        })
        .get(|| async {
            (
                StatusCode::PARTIAL_CONTENT,
                [
                    (header::CONTENT_TYPE, "video/mp4"),
                    (header::CONTENT_RANGE, "bytes 0-3/16"),
                    (header::CONTENT_LENGTH, "4"),
                ],
                "ftyp",
            )
        }),
    );
    let ostore_url = spawn_server(ostore_app).await;

    let h = hash.to_string();
    let bt_app = Router::new().route(
        "/api/check/{hash}",
        get(move || {
            let h = h.clone();
            async move {
                Json(serde_json::json!({
                    "hash": h,
                    "cached": false,
                    "head_ready": false,
                    "path": "",
                    "size": 0,
                    "mime": "video/mp4"
                }))
            }
        }),
    );
    let bt_url = spawn_server(bt_app).await;

    let cfg = Arc::new(Config {
        bind_addr: "127.0.0.1:0".parse().expect("valid addr"),
        node_id: "cc".to_string(),
        token: Some("secret-tok".to_string()),
        bt_url: Some(bt_url),
        ostore_url: Some(ostore_url),
        ostore_token: Some("ostore-tok".to_string()),
        media_prefix: "xstream/media".to_string(),
        bt_cache_dir: PathBuf::from("/tmp"),
        work_dir: PathBuf::from("/tmp/omesh-test-work"),
        peers: Vec::<PeerSpec>::new(),
    });
    let client = Client::new();
    let peers = PeerRegistry::new(Vec::new());
    let jobs = JobManager::new(Arc::clone(&cfg), client.clone(), peers.clone());
    let state = AppState {
        config: cfg,
        client,
        peers,
        jobs,
    };
    spawn_server(build_router(state)).await
}

#[tokio::test]
async fn ostore_cdn_hit_beats_bt_and_streams_range() {
    let hash = "a".repeat(40);
    let omesh_url = spawn_mock_mesh(&hash).await;
    let client = Client::new();

    // 1. /api/check hits ostore CDN.
    let check: StreamCheckDto = client
        .get(format!("{omesh_url}/api/check/{hash}"))
        .send()
        .await
        .expect("check request")
        .json()
        .await
        .expect("decode check");
    assert!(check.head_ready, "ostore hit must be head_ready");
    assert_eq!(check.source, "ostore", "source must be ostore");
    assert_eq!(check.size, 16, "size matches Content-Length");

    // 2. /stream serves Range from ostore with X-Omesh-Source header.
    let stream_resp = client
        .get(format!("{omesh_url}/stream/{hash}"))
        .header(header::RANGE, "bytes=0-3")
        .send()
        .await
        .expect("stream request");
    assert_eq!(
        stream_resp.status(),
        StatusCode::PARTIAL_CONTENT,
        "206 Partial Content"
    );
    assert_eq!(
        stream_resp
            .headers()
            .get("x-omesh-source")
            .and_then(|v| v.to_str().ok()),
        Some("ostore"),
        "source header must identify ostore"
    );
    let body = stream_resp.text().await.expect("read body");
    assert_eq!(body, "ftyp", "proxied Range bytes match");

    // 3. /mesh/nodes enforces Bearer auth.
    let unauth = client
        .get(format!("{omesh_url}/mesh/nodes"))
        .send()
        .await
        .expect("unauth request");
    assert_eq!(
        unauth.status(),
        StatusCode::UNAUTHORIZED,
        "missing token rejected"
    );

    let authed = client
        .get(format!("{omesh_url}/mesh/nodes"))
        .bearer_auth("secret-tok")
        .send()
        .await
        .expect("authed request");
    assert_eq!(authed.status(), StatusCode::OK, "valid token accepted");
}
