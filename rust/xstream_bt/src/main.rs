//! Binary entrypoint for the `xstream_bt` `BitTorrent` streaming daemon.

use std::{sync::Arc, time::Duration};

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
        max_cache_bytes = config.max_cache_bytes,
        evict_interval_secs = config.evict_interval_secs,
        "starting xstream_bt"
    );

    let engine = match BtEngine::new(&config).await {
        Ok(engine) => Arc::new(engine),
        Err(err) => {
            error!(error = %err, "failed to initialize BtEngine");
            std::process::exit(1);
        }
    };

    // Background disk-quota enforcer: keeps disk usage strictly within max_cache_bytes.
    let evict_engine = Arc::clone(&engine);
    let evict_interval = Duration::from_secs(config.evict_interval_secs);
    tokio::spawn(async move {
        let mut ticker = tokio::time::interval(evict_interval);
        ticker.tick().await;
        loop {
            ticker.tick().await;
            let res = evict_engine.enforce_quota().await;
            if !res.evicted_hashes.is_empty() {
                info!(
                    evicted = res.evicted_hashes.len(),
                    freed_bytes = res.freed_bytes,
                    used_bytes = res.used_bytes,
                    max_bytes = res.max_bytes,
                    "quota sweep reclaimed cache space"
                );
            }
        }
    });

    // Background QoS restorer: resumes yielded background downloads once playback goes idle.
    let qos_engine = Arc::clone(&engine);
    tokio::spawn(async move {
        let mut ticker = tokio::time::interval(Duration::from_secs(5));
        ticker.tick().await;
        loop {
            ticker.tick().await;
            qos_engine.restore_yielded_if_idle().await;
        }
    });

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
