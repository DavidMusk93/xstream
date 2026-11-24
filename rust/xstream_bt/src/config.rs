//! Environment-driven configuration for `xstream_bt`.

use std::{env, net::SocketAddr, path::PathBuf};

/// Runtime configuration for the `BitTorrent` streaming daemon.
#[derive(Debug, Clone)]
pub struct Config {
    /// HTTP bind address (default `127.0.0.1:8766`).
    pub bind_addr: SocketAddr,
    /// Directory where `librqbit` stores torrent payloads and persistence state.
    pub cache_dir: PathBuf,
    /// `BitTorrent` TCP/UDP listen port (default `6882`).
    pub bt_listen_port: u16,
}

impl Config {
    /// Load configuration from environment variables with sensible defaults.
    ///
    /// Supported variables:
    /// - `XSTREAM_BT_BIND` (default `127.0.0.1:8766`)
    /// - `XSTREAM_BT_CACHE_DIR` (default `/root/xstream/cache/rqbit`)
    /// - `XSTREAM_BT_LISTEN_PORT` (default `6882`)
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

        Self {
            bind_addr,
            cache_dir,
            bt_listen_port,
        }
    }
}
