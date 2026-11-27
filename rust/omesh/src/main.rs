//! `omesh` daemon binary entry point.

use std::{sync::Arc, time::Duration};

use omesh::{
    config::Config,
    jobs::JobManager,
    peer::PeerRegistry,
    router::{build_router, AppState},
};
use reqwest::Client;
use tokio::net::TcpListener;
use tracing::{error, info};
use tracing_subscriber::EnvFilter;

#[tokio::main]
async fn main() {
    tracing_subscriber::fmt()
        .with_env_filter(
            EnvFilter::try_from_default_env().unwrap_or_else(|_| EnvFilter::new("omesh=info")),
        )
        .init();

    let config = Arc::new(Config::from_env());
    let client = match Client::builder()
        .connect_timeout(Duration::from_secs(3))
        .pool_idle_timeout(Duration::from_secs(60))
        .build()
    {
        Ok(c) => c,
        Err(err) => {
            error!(error = %err, "failed to build HTTP client");
            std::process::exit(1);
        }
    };

    let peers = PeerRegistry::new(config.peers.clone());
    let jobs = JobManager::new(Arc::clone(&config), client.clone(), peers.clone());

    // Initial peer probe + periodic 15s background health check.
    peers.probe_all(&client).await;
    {
        let peers_bg = peers.clone();
        let client_bg = client.clone();
        tokio::spawn(async move {
            let mut interval = tokio::time::interval(Duration::from_secs(15));
            interval.tick().await;
            loop {
                interval.tick().await;
                peers_bg.probe_all(&client_bg).await;
            }
        });
    }

    let state = AppState {
        config: Arc::clone(&config),
        client,
        peers,
        jobs,
    };

    let app = build_router(state);
    let listener = match TcpListener::bind(config.bind_addr).await {
        Ok(l) => l,
        Err(err) => {
            error!(bind = %config.bind_addr, error = %err, "failed to bind omesh listener");
            std::process::exit(1);
        }
    };

    info!(
        node_id = %config.node_id,
        bind = %config.bind_addr,
        ostore = ?config.ostore_url,
        bt = ?config.bt_url,
        peers = config.peers.len(),
        "omesh listening"
    );

    if let Err(err) = axum::serve(listener, app)
        .with_graceful_shutdown(shutdown_signal())
        .await
    {
        error!(error = %err, "omesh server error");
        std::process::exit(1);
    }
}

async fn shutdown_signal() {
    let ctrl_c = async {
        let _ = tokio::signal::ctrl_c().await;
    };
    #[cfg(unix)]
    let terminate = async {
        if let Ok(mut sig) =
            tokio::signal::unix::signal(tokio::signal::unix::SignalKind::terminate())
        {
            sig.recv().await;
        }
    };
    #[cfg(not(unix))]
    let terminate = std::future::pending::<()>();

    tokio::select! {
        () = ctrl_c => {},
        () = terminate => {},
    }
    info!("omesh shutting down");
}
