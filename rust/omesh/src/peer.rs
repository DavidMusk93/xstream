//! Mesh peer discovery, health telemetry, and pure compute-worker selection.

use std::{
    sync::{Arc, RwLock},
    time::{Duration, Instant},
};

use reqwest::Client;
use serde::{Deserialize, Serialize};
use tracing::debug;

use crate::config::PeerSpec;

/// Health payload returned by `GET /health` on every `omesh` node.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct NodeHealth {
    /// Always `true` when the node is serving.
    pub ok: bool,
    /// Node identifier (e.g. `"cc"`, `"cc2"`, `"rn"`).
    pub node_id: String,
    /// Whether this node has a local `xstream_bt` backend configured.
    pub bt_enabled: bool,
    /// Whether this node has an `ostore` backend configured.
    pub ostore_enabled: bool,
    /// Number of currently running compute jobs on this node.
    pub active_jobs: usize,
    /// Approximate free disk bytes in the node's work directory (0 if unknown).
    pub free_disk_bytes: u64,
}

/// Live status snapshot of a mesh peer node.
#[derive(Debug, Clone, Serialize)]
pub struct PeerSnapshot {
    /// Peer node identifier.
    pub id: String,
    /// Peer base HTTP URL.
    pub url: String,
    /// Whether the most recent health probe succeeded.
    pub healthy: bool,
    /// Measured HTTP round-trip latency in milliseconds.
    pub rtt_ms: u64,
    /// Whether the peer has a local `xstream_bt` daemon.
    pub bt_enabled: bool,
    /// Number of active compute jobs reported by the peer.
    pub active_jobs: usize,
    /// Reported free disk bytes on the peer.
    pub free_disk_bytes: u64,
}

/// Thread-safe registry tracking health and RTT of remote `omesh` peers.
#[derive(Debug, Clone)]
pub struct PeerRegistry {
    specs: Arc<[PeerSpec]>,
    snapshots: Arc<RwLock<Vec<PeerSnapshot>>>,
}

impl PeerRegistry {
    /// Create a registry seeded with `specs` (initially marked unhealthy until first probe).
    pub fn new(specs: Vec<PeerSpec>) -> Self {
        let initial = specs
            .iter()
            .map(|p| PeerSnapshot {
                id: p.id.clone(),
                url: p.url.clone(),
                healthy: false,
                rtt_ms: 0,
                bt_enabled: false,
                active_jobs: 0,
                free_disk_bytes: 0,
            })
            .collect();
        Self {
            specs: Arc::from(specs),
            snapshots: Arc::new(RwLock::new(initial)),
        }
    }

    /// Return all peer snapshots ordered by health and lowest RTT.
    pub fn list(&self) -> Vec<PeerSnapshot> {
        self.snapshots
            .read()
            .map_or_else(|_| Vec::new(), |g| g.clone())
    }

    /// Return currently healthy peers sorted by lowest RTT first.
    pub fn healthy_peers(&self) -> Vec<PeerSnapshot> {
        let mut peers: Vec<PeerSnapshot> = self.list().into_iter().filter(|p| p.healthy).collect();
        peers.sort_by_key(|p| p.rtt_ms);
        peers
    }

    /// Select the best healthy remote worker for compute offload.
    pub fn best_worker(&self) -> Option<PeerSnapshot> {
        let list = self.list();
        select_best_worker(&list).cloned()
    }

    /// Probe all configured peers in parallel and update their live snapshots.
    pub async fn probe_all(&self, client: &Client) {
        if self.specs.is_empty() {
            return;
        }
        let mut tasks = Vec::with_capacity(self.specs.len());
        for spec in self.specs.iter() {
            let client = client.clone();
            let spec = spec.clone();
            tasks.push(tokio::spawn(async move { probe_one(&client, &spec).await }));
        }

        let mut next = Vec::with_capacity(tasks.len());
        for task in tasks {
            if let Ok(snap) = task.await {
                next.push(snap);
            }
        }
        if let Ok(mut guard) = self.snapshots.write() {
            *guard = next;
        }
    }
}

async fn probe_one(client: &Client, spec: &PeerSpec) -> PeerSnapshot {
    let url = format!("{}/health", spec.url);
    let started = Instant::now();
    let res = client
        .get(&url)
        .timeout(Duration::from_secs(2))
        .send()
        .await;
    let rtt_ms = u64::try_from(started.elapsed().as_millis()).unwrap_or(u64::MAX);

    match res {
        Ok(resp) if resp.status().is_success() => {
            if let Ok(h) = resp.json::<NodeHealth>().await {
                return PeerSnapshot {
                    id: spec.id.clone(),
                    url: spec.url.clone(),
                    healthy: h.ok,
                    rtt_ms,
                    bt_enabled: h.bt_enabled,
                    active_jobs: h.active_jobs,
                    free_disk_bytes: h.free_disk_bytes,
                };
            }
            PeerSnapshot {
                id: spec.id.clone(),
                url: spec.url.clone(),
                healthy: false,
                rtt_ms,
                bt_enabled: false,
                active_jobs: 0,
                free_disk_bytes: 0,
            }
        }
        Ok(resp) => {
            debug!(peer = %spec.id, status = %resp.status(), "peer health check non-200");
            PeerSnapshot {
                id: spec.id.clone(),
                url: spec.url.clone(),
                healthy: false,
                rtt_ms,
                bt_enabled: false,
                active_jobs: 0,
                free_disk_bytes: 0,
            }
        }
        Err(err) => {
            debug!(peer = %spec.id, error = %err, "peer health check failed");
            PeerSnapshot {
                id: spec.id.clone(),
                url: spec.url.clone(),
                healthy: false,
                rtt_ms,
                bt_enabled: false,
                active_jobs: 0,
                free_disk_bytes: 0,
            }
        }
    }
}

/// Pure deterministic scheduler: pick the best healthy worker for compute offload.
///
/// Prefers fewer active jobs, then larger free disk space, then lower RTT, then lexicographic ID.
pub fn select_best_worker(peers: &[PeerSnapshot]) -> Option<&PeerSnapshot> {
    peers.iter().filter(|p| p.healthy).min_by(|a, b| {
        a.active_jobs
            .cmp(&b.active_jobs)
            .then_with(|| b.free_disk_bytes.cmp(&a.free_disk_bytes))
            .then_with(|| a.rtt_ms.cmp(&b.rtt_ms))
            .then_with(|| a.id.cmp(&b.id))
    })
}

#[cfg(test)]
mod tests {
    use super::*;

    #[derive(Clone, Copy)]
    enum Health {
        Up,
        Down,
    }

    fn mk(id: &str, health: Health, active_jobs: usize, free_gb: u64, rtt_ms: u64) -> PeerSnapshot {
        PeerSnapshot {
            id: id.to_string(),
            url: format!("http://{id}:8767"),
            healthy: matches!(health, Health::Up),
            rtt_ms,
            bt_enabled: true,
            active_jobs,
            free_disk_bytes: free_gb * 1024 * 1024 * 1024,
        }
    }

    #[test]
    fn picks_idle_worker_with_most_free_disk() {
        let peers = vec![
            mk("cc2", Health::Up, 0, 7, 1),
            mk("rn", Health::Up, 0, 25, 2),
            mk("down", Health::Down, 0, 500, 0),
        ];
        let picked = select_best_worker(&peers).expect("healthy peer exists");
        assert_eq!(
            picked.id, "rn",
            "should prefer rn with 25 GiB free over cc2 with 7 GiB"
        );
    }

    #[test]
    fn avoids_busy_worker_when_idle_peer_exists() {
        let peers = vec![
            mk("rn", Health::Up, 2, 25, 2),
            mk("cc2", Health::Up, 0, 7, 1),
        ];
        let picked = select_best_worker(&peers).expect("healthy peer exists");
        assert_eq!(picked.id, "cc2", "should prefer idle cc2 over busy rn");
    }

    #[test]
    fn returns_none_when_no_healthy_peers() {
        let peers = vec![mk("rn", Health::Down, 0, 25, 2)];
        assert!(select_best_worker(&peers).is_none(), "no healthy worker");
    }
}
