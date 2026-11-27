//! Environment-driven configuration for `omesh`.

use std::{env, net::SocketAddr, path::PathBuf};

/// A remote `omesh` peer node configured via `OMESH_PEERS`.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct PeerSpec {
    /// Short node identifier (e.g. `"cc2"`, `"rn"`).
    pub id: String,
    /// Base HTTP URL of the peer's `omesh` daemon (e.g. `"http://113.20.5.130:8767"`).
    pub url: String,
}

/// Runtime configuration for the `omesh` compute & HTTP CDN edge daemon.
#[derive(Debug, Clone)]
pub struct Config {
    /// HTTP bind address (default `127.0.0.1:8767`).
    pub bind_addr: SocketAddr,
    /// Local node identifier (default `"cc"`).
    pub node_id: String,
    /// Shared Bearer token for peer-to-peer and job APIs (optional for local-only mode).
    pub token: Option<String>,
    /// Local `xstream_bt` base URL (e.g. `"http://127.0.0.1:8766"`).
    pub bt_url: Option<String>,
    /// Local `ostore` base URL (e.g. `"http://127.0.0.1:8781"`).
    pub ostore_url: Option<String>,
    /// Bearer token for `ostore` API requests.
    pub ostore_token: Option<String>,
    /// Object key prefix inside `ostore` for archived fast-start media (default `"xstream/media"`).
    pub media_prefix: String,
    /// Local `xstream_bt` cache directory for direct faststart reads (default `"/root/xstream/cache/rqbit"`).
    pub bt_cache_dir: PathBuf,
    /// Scratch directory for lossless `ffmpeg -movflags +faststart` remuxing.
    pub work_dir: PathBuf,
    /// Remote `omesh` peer nodes in the mesh.
    pub peers: Vec<PeerSpec>,
}

impl Config {
    /// Load configuration from environment variables with sensible defaults.
    pub fn from_env() -> Self {
        let bind_addr = env::var("OMESH_BIND")
            .ok()
            .and_then(|v| v.parse::<SocketAddr>().ok())
            .unwrap_or_else(|| SocketAddr::from(([127, 0, 0, 1], 8767)));

        let node_id = non_empty_env("OMESH_NODE_ID").unwrap_or_else(|| "cc".to_string());
        let ostore_token =
            non_empty_env("OMESH_OSTORE_TOKEN").or_else(|| non_empty_env("OSTORE_TOKEN"));
        let token = non_empty_env("OMESH_TOKEN").or_else(|| ostore_token.clone());

        let bt_url = non_empty_env("OMESH_BT_URL")
            .or_else(|| non_empty_env("XSTREAM_BT_URL"))
            .map(|u| u.trim_end_matches('/').to_string());

        let ostore_url =
            non_empty_env("OMESH_OSTORE_URL").map(|u| u.trim_end_matches('/').to_string());

        let media_prefix = non_empty_env("OMESH_MEDIA_PREFIX")
            .unwrap_or_else(|| "xstream/media".to_string())
            .trim_matches('/')
            .to_string();

        let bt_cache_dir = non_empty_env("OMESH_BT_CACHE_DIR")
            .map_or_else(|| PathBuf::from("/root/xstream/cache/rqbit"), PathBuf::from);

        let work_dir = non_empty_env("OMESH_WORK_DIR")
            .map_or_else(|| PathBuf::from("/tmp/omesh-work"), PathBuf::from);

        let peers = non_empty_env("OMESH_PEERS")
            .map(|raw| parse_peers(&raw))
            .unwrap_or_default();

        Self {
            bind_addr,
            node_id,
            token,
            bt_url,
            ostore_url,
            ostore_token,
            media_prefix,
            bt_cache_dir,
            work_dir,
            peers,
        }
    }
}

fn non_empty_env(name: &str) -> Option<String> {
    env::var(name)
        .ok()
        .map(|v| v.trim().to_string())
        .filter(|v| !v.is_empty())
}

/// Parse `OMESH_PEERS` entries of the form `"cc2=http://113.20.5.130:8767,rn=http://192.129.240.103:8767"`.
pub fn parse_peers(raw: &str) -> Vec<PeerSpec> {
    raw.split(',')
        .filter_map(|entry| {
            let trimmed = entry.trim();
            if trimmed.is_empty() {
                return None;
            }
            let (id, url) = trimmed.split_once('=')?;
            let id = id.trim();
            let url = url.trim().trim_end_matches('/');
            if id.is_empty() || url.is_empty() {
                return None;
            }
            Some(PeerSpec {
                id: id.to_string(),
                url: url.to_string(),
            })
        })
        .collect()
}

/// Validate and normalize a 40-character hexadecimal `BitTorrent` info-hash.
pub fn normalize_hash(raw: &str) -> Option<String> {
    let trimmed = raw.trim();
    if trimmed.len() == 40 && trimmed.bytes().all(|b| b.is_ascii_hexdigit()) {
        Some(trimmed.to_ascii_lowercase())
    } else {
        None
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn parses_comma_separated_peers() {
        let peers =
            parse_peers("cc2=http://113.20.5.130:8767/, rn = http://192.129.240.103:8767 , bad");
        assert_eq!(peers.len(), 2, "expected two valid peers");
        assert_eq!(peers[0].id, "cc2", "first peer id");
        assert_eq!(
            peers[0].url, "http://113.20.5.130:8767",
            "trailing slash stripped"
        );
        assert_eq!(peers[1].id, "rn", "second peer id");
        assert_eq!(
            peers[1].url, "http://192.129.240.103:8767",
            "second peer url"
        );
    }

    #[test]
    fn normalizes_hex_hashes() {
        assert_eq!(
            normalize_hash("50EDA3B679EB1E1468FE53B5D2A37BA94DFD2835"),
            Some("50eda3b679eb1e1468fe53b5d2a37ba94dfd2835".to_string()),
            "uppercase hex normalizes to lowercase"
        );
        assert_eq!(normalize_hash("short"), None, "short hash rejected");
        assert_eq!(
            normalize_hash("zzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzz"),
            None,
            "non-hex rejected"
        );
    }
}
