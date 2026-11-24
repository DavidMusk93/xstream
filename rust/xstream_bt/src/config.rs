//! Environment-driven configuration for `xstream_bt`.

use std::{env, net::SocketAddr, path::PathBuf};

/// Default maximum disk cache size in GiB (20 GiB).
const DEFAULT_MAX_CACHE_GB: u64 = 20;

/// Default background quota enforcement interval in seconds.
const DEFAULT_EVICT_INTERVAL_SECS: u64 = 30;

/// Runtime configuration for the `BitTorrent` streaming daemon.
#[derive(Debug, Clone)]
pub struct Config {
    /// HTTP bind address (default `127.0.0.1:8766`).
    pub bind_addr: SocketAddr,
    /// Directory where `librqbit` stores torrent payloads and persistence state.
    pub cache_dir: PathBuf,
    /// `BitTorrent` TCP/UDP listen port (default `6882`).
    pub bt_listen_port: u16,
    /// Disk cache budget in bytes (`XSTREAM_BT_MAX_CACHE_GB`, default 20 GiB).
    pub max_cache_bytes: u64,
    /// Interval in seconds between background quota enforcement sweeps (default 30s).
    pub evict_interval_secs: u64,
}

impl Config {
    /// Load configuration from environment variables with sensible defaults.
    ///
    /// Supported variables:
    /// - `XSTREAM_BT_BIND` (default `127.0.0.1:8766`)
    /// - `XSTREAM_BT_CACHE_DIR` (default `/root/xstream/cache/rqbit`)
    /// - `XSTREAM_BT_LISTEN_PORT` (default `6882`)
    /// - `XSTREAM_BT_MAX_CACHE_GB` (default `20`)
    /// - `XSTREAM_BT_EVICT_INTERVAL_SECS` (default `30`)
    pub fn from_env() -> Self {
        let bind_addr = env::var("XSTREAM_BT_BIND")
            .ok()
            .and_then(|v| v.parse::<SocketAddr>().ok())
            .unwrap_or_else(|| SocketAddr::from(([127, 0, 0, 1], 8766)));

        let cache_dir = env::var("XSTREAM_BT_CACHE_DIR").map_or_else(
            |_| PathBuf::from("/root/xstream/cache/rqbit"),
            PathBuf::from,
        );

        let bt_listen_port = env::var("XSTREAM_BT_LISTEN_PORT")
            .ok()
            .and_then(|v| v.parse::<u16>().ok())
            .unwrap_or(6882);

        let max_cache_gb = env::var("XSTREAM_BT_MAX_CACHE_GB")
            .ok()
            .and_then(|v| v.parse::<u64>().ok())
            .unwrap_or(DEFAULT_MAX_CACHE_GB);

        let evict_interval_secs = env::var("XSTREAM_BT_EVICT_INTERVAL_SECS")
            .ok()
            .and_then(|v| v.parse::<u64>().ok())
            .unwrap_or(DEFAULT_EVICT_INTERVAL_SECS)
            .max(5);

        Self {
            bind_addr,
            cache_dir,
            bt_listen_port,
            max_cache_bytes: max_cache_gb.saturating_mul(1024 * 1024 * 1024),
            evict_interval_secs,
        }
    }
}
