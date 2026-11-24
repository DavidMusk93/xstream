//! Binary entrypoint for the `xstream_bt` `BitTorrent` streaming daemon.

use std::sync::Arc;

use tokio::{net::TcpListener, signal};
use tracing::{error, info};
use tracing_subscriber::EnvFilter;

use xstream_bt::{config::Config, engine::BtEngine, http::build_router};

#[tokio::main]
async fn main() {
    let filter = EnvFilter::try_from_default_env()
        .unwrap_or_else(|_| EnvFilter::new("xstream_bt=info,librqbit=warn"));
    tracing_subscriber::fmt().with_env_filter(filter).init();

    let config = Config::from_env();
    info!(
        bind = %config.bind_addr,
        cache_dir = %config.cache_dir.display(),
        bt_port = config.bt_listen_port,
        "starting xstream_bt"
    );

    let engine = match BtEngine::new(&config).await {
        Ok(engine) => Arc::new(engine),
        Err(err) => {
            error!(error = %err, "failed to initialize BtEngine");
            std::process::exit(1);
        }
    };

    let router = build_router(engine);
    let listener = match TcpListener::bind(config.bind_addr).await {
        Ok(listener) => listener,
        Err(err) => {
            error!(bind = %config.bind_addr, error = %err, "failed to bind TCP listener");
            std::process::exit(1);
        }
    };

    info!(bind = %config.bind_addr, "xstream_bt listening");

    if let Err(err) = axum::serve(listener, router)
        .with_graceful_shutdown(shutdown_signal())
        .await
    {
        error!(error = %err, "HTTP server exited with error");
        std::process::exit(1);
    }

    info!("xstream_bt shut down cleanly");
}

async fn shutdown_signal() {
    let ctrl_c = async {
        let _ = signal::ctrl_c().await;
    };

    #[cfg(unix)]
    let terminate = async {
        if let Ok(mut sig) = signal::unix::signal(signal::unix::SignalKind::terminate()) {
            sig.recv().await;
        }
    };

    #[cfg(not(unix))]
    let terminate = std::future::pending::<()>();

    tokio::select! {
        () = ctrl_c => {},
        () = terminate => {},
    }
}
