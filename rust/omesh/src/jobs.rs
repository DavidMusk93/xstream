//! Compute job runner for `omesh` (lossless MP4 `faststart` remux + `ostore` archival + peer offload).

use std::{
    collections::HashMap,
    path::{Path, PathBuf},
    sync::{
        atomic::{AtomicU64, Ordering},
        Arc, RwLock,
    },
    time::{SystemTime, UNIX_EPOCH},
};

use futures_util::StreamExt;
use reqwest::Client;
use serde::{Deserialize, Serialize};
use tokio::{fs, io::AsyncWriteExt, process::Command};
use tokio_util::io::ReaderStream;
use tracing::{info, warn};

#[derive(Deserialize)]
struct BtStatus {
    video_file: Option<String>,
    progress: f64,
}

use crate::{
    config::{normalize_hash, Config},
    error::MeshError,
    peer::PeerRegistry,
};

/// Requested compute job payload submitted to `POST /mesh/jobs`.
#[derive(Debug, Clone, Deserialize, Serialize)]
#[serde(tag = "kind", rename_all = "snake_case")]
#[non_exhaustive]
pub enum JobSpec {
    /// Remux a completed local `xstream_bt` video with `-movflags +faststart` and upload to `ostore`.
    FaststartArchive {
        /// 40-char hex `BitTorrent` info-hash.
        hash: String,
        /// Optional target node (`"local"`, `"auto"`, or a specific peer ID like `"rn"`).
        #[serde(default)]
        target: Option<String>,
    },
    /// Download an existing `ostore` MP4, remux with `-movflags +faststart`, and re-upload to `ostore`.
    FaststartOstore {
        /// Source object path inside `ostore`.
        source_path: String,
        /// Destination object path inside `ostore` (defaults to overwriting `source_path`).
        #[serde(default)]
        dest_path: Option<String>,
        /// Optional target node (`"local"`, `"auto"`, or a specific peer ID).
        #[serde(default)]
        target: Option<String>,
    },
}

/// Lifecycle state of a compute job.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
#[non_exhaustive]
pub enum JobState {
    /// Queued and waiting to execute.
    Queued,
    /// Actively executing.
    Running,
    /// Forwarded to a remote peer worker.
    Dispatched,
    /// Completed successfully.
    Done,
    /// Failed with an error message.
    Failed,
}

/// Public job record returned by `POST /mesh/jobs` and `GET /mesh/jobs/{id}`.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct JobRecord {
    /// Unique job identifier.
    pub id: String,
    /// Node that accepted or executed the job.
    pub node_id: String,
    /// Current lifecycle state.
    pub state: JobState,
    /// Human-readable summary or output object path.
    pub detail: String,
    /// Unix creation timestamp in seconds.
    pub created_at: u64,
    /// Unix last-update timestamp in seconds.
    pub updated_at: u64,
}

/// Thread-safe in-memory job registry and async executor.
#[derive(Debug, Clone)]
pub struct JobManager {
    config: Arc<Config>,
    client: Client,
    peers: PeerRegistry,
    next_id: Arc<AtomicU64>,
    jobs: Arc<RwLock<HashMap<String, JobRecord>>>,
}

impl JobManager {
    /// Construct a new [`JobManager`].
    pub fn new(config: Arc<Config>, client: Client, peers: PeerRegistry) -> Self {
        Self {
            config,
            client,
            peers,
            next_id: Arc::new(AtomicU64::new(1)),
            jobs: Arc::new(RwLock::new(HashMap::new())),
        }
    }

    /// Count of currently active (`Queued` or `Running`) jobs on this node.
    pub fn active_count(&self) -> usize {
        self.jobs.read().map_or(0, |map| {
            map.values()
                .filter(|j| matches!(j.state, JobState::Queued | JobState::Running))
                .count()
        })
    }

    /// Return all known job records ordered newest first.
    pub fn list(&self) -> Vec<JobRecord> {
        let mut out: Vec<JobRecord> = self
            .jobs
            .read()
            .map_or_else(|_| Vec::new(), |map| map.values().cloned().collect());
        out.sort_by(|a, b| {
            b.created_at
                .cmp(&a.created_at)
                .then_with(|| b.id.cmp(&a.id))
        });
        out
    }

    /// Look up a single job by ID.
    pub fn get(&self, id: &str) -> Option<JobRecord> {
        self.jobs.read().ok().and_then(|map| map.get(id).cloned())
    }

    /// Submit a new compute job, optionally dispatching it to a healthy remote peer.
    ///
    /// # Errors
    /// Returns [`MeshError::InvalidInput`] for invalid hashes or paths, or [`MeshError::Upstream`]
    /// if remote dispatch fails.
    pub async fn submit(&self, spec: JobSpec) -> Result<JobRecord, MeshError> {
        let target = match &spec {
            JobSpec::FaststartArchive { hash, target } => {
                if normalize_hash(hash).is_none() {
                    return Err(MeshError::InvalidInput(
                        "invalid 40-char hex hash".to_string(),
                    ));
                }
                target.as_deref()
            }
            JobSpec::FaststartOstore {
                source_path,
                target,
                ..
            } => {
                if source_path.trim().is_empty() || source_path.contains("..") {
                    return Err(MeshError::InvalidInput("invalid source_path".to_string()));
                }
                target.as_deref()
            }
        };

        // Remote compute offload when requested (`"auto"` or explicit peer ID).
        if let Some(peer) = self.resolve_remote_target(target) {
            return self.dispatch_to_peer(&peer.id, &peer.url, spec).await;
        }

        let seq = self.next_id.fetch_add(1, Ordering::Relaxed);
        let now = unix_now();
        let id = format!("{}-{now}-{seq}", self.config.node_id);
        let rec = JobRecord {
            id: id.clone(),
            node_id: self.config.node_id.clone(),
            state: JobState::Queued,
            detail: "queued".to_string(),
            created_at: now,
            updated_at: now,
        };
        if let Ok(mut map) = self.jobs.write() {
            map.insert(id.clone(), rec.clone());
        }

        let mgr = self.clone();
        let job_id = id;
        tokio::spawn(async move {
            mgr.update_job(&job_id, JobState::Running, "running");
            let res = match spec {
                JobSpec::FaststartArchive { hash, .. } => mgr.run_faststart_archive(&hash).await,
                JobSpec::FaststartOstore {
                    source_path,
                    dest_path,
                    ..
                } => {
                    mgr.run_faststart_ostore(&source_path, dest_path.as_deref())
                        .await
                }
            };
            match res {
                Ok(detail) => {
                    info!(job_id = %job_id, detail = %detail, "compute job completed");
                    mgr.update_job(&job_id, JobState::Done, detail);
                }
                Err(err) => {
                    warn!(job_id = %job_id, error = %err, "compute job failed");
                    mgr.update_job(&job_id, JobState::Failed, err.to_string());
                }
            }
        });

        Ok(rec)
    }

    fn resolve_remote_target(&self, target: Option<&str>) -> Option<crate::peer::PeerSnapshot> {
        match target {
            Some("auto") => self.peers.best_worker(),
            Some("local") | None => None,
            Some(peer_id) if peer_id == self.config.node_id => None,
            Some(peer_id) => self
                .peers
                .healthy_peers()
                .into_iter()
                .find(|p| p.id == peer_id),
        }
    }

    async fn dispatch_to_peer(
        &self,
        peer_id: &str,
        peer_url: &str,
        spec: JobSpec,
    ) -> Result<JobRecord, MeshError> {
        let pinned_spec = match spec {
            JobSpec::FaststartArchive { hash, .. } => JobSpec::FaststartArchive {
                hash,
                target: Some("local".to_string()),
            },
            JobSpec::FaststartOstore {
                source_path,
                dest_path,
                ..
            } => JobSpec::FaststartOstore {
                source_path,
                dest_path,
                target: Some("local".to_string()),
            },
        };

        let mut req = self
            .client
            .post(format!("{peer_url}/mesh/jobs"))
            .json(&pinned_spec);
        if let Some(tok) = &self.config.token {
            req = req.bearer_auth(tok);
        }
        let resp = req
            .send()
            .await
            .map_err(|err| MeshError::Upstream(format!("dispatch to {peer_id} failed: {err}")))?;
        if !resp.status().is_success() {
            let status = resp.status();
            let body = resp.text().await.unwrap_or_default();
            return Err(MeshError::Upstream(format!(
                "peer {peer_id} rejected job ({status}): {body}"
            )));
        }
        let mut remote = resp
            .json::<JobRecord>()
            .await
            .map_err(|err| MeshError::Upstream(format!("invalid peer job response: {err}")))?;
        remote.state = JobState::Dispatched;
        if let Ok(mut map) = self.jobs.write() {
            map.insert(remote.id.clone(), remote.clone());
        }
        Ok(remote)
    }

    fn update_job(&self, id: &str, state: JobState, detail: impl Into<String>) {
        if let Ok(mut map) = self.jobs.write() {
            if let Some(entry) = map.get_mut(id) {
                entry.state = state;
                entry.detail = detail.into();
                entry.updated_at = unix_now();
            }
        }
    }

    async fn run_faststart_archive(&self, raw_hash: &str) -> Result<String, MeshError> {
        let hash = normalize_hash(raw_hash)
            .ok_or_else(|| MeshError::InvalidInput("invalid info-hash".to_string()))?;
        let bt_url = self
            .config
            .bt_url
            .as_deref()
            .ok_or_else(|| MeshError::Internal("OMESH_BT_URL not configured".to_string()))?;
        let ostore_url =
            self.config.ostore_url.as_deref().ok_or_else(|| {
                MeshError::Internal("OMESH_OSTORE_URL not configured".to_string())
            })?;

        let status_resp = self
            .client
            .get(format!("{bt_url}/torrent/status/{hash}"))
            .send()
            .await
            .map_err(|err| MeshError::Upstream(format!("xstream_bt status failed: {err}")))?;
        if !status_resp.status().is_success() {
            return Err(MeshError::NotFound(format!(
                "torrent {hash} not found in local xstream_bt"
            )));
        }

        let st: BtStatus = status_resp
            .json()
            .await
            .map_err(|err| MeshError::Upstream(format!("parse xstream_bt status: {err}")))?;
        if st.progress < 99.9 {
            return Err(MeshError::InvalidInput(format!(
                "torrent {hash} is only {:.1}% downloaded; wait for completion before archiving",
                st.progress
            )));
        }
        let rel = st
            .video_file
            .ok_or_else(|| MeshError::NotFound(format!("no video file for {hash}")))?;

        let src_path = self.config.bt_cache_dir.join(&rel);
        if !src_path.exists() {
            return Err(MeshError::NotFound(format!(
                "local video missing at {}",
                src_path.display()
            )));
        }

        fs::create_dir_all(&self.config.work_dir)
            .await
            .map_err(|err| MeshError::Internal(format!("create work_dir failed: {err}")))?;
        let out_path = self.config.work_dir.join(format!("{hash}.faststart.mp4"));

        run_ffmpeg_faststart(&src_path, &out_path).await?;
        let dest_key = format!("{}/{hash}.mp4", self.config.media_prefix);
        let upload_res = self
            .upload_file_to_ostore(ostore_url, &dest_key, &out_path)
            .await;
        let _ = fs::remove_file(&out_path).await;
        upload_res?;

        Ok(format!("archived to ostore:{dest_key}"))
    }

    async fn run_faststart_ostore(
        &self,
        source_path: &str,
        dest_path: Option<&str>,
    ) -> Result<String, MeshError> {
        let ostore_url =
            self.config.ostore_url.as_deref().ok_or_else(|| {
                MeshError::Internal("OMESH_OSTORE_URL not configured".to_string())
            })?;
        let src_key = source_path.trim_start_matches('/');
        let dst_key = dest_path.unwrap_or(src_key).trim_start_matches('/');

        fs::create_dir_all(&self.config.work_dir)
            .await
            .map_err(|err| MeshError::Internal(format!("create work_dir failed: {err}")))?;
        let stamp = unix_now();
        let in_path = self.config.work_dir.join(format!("in-{stamp}.mp4"));
        let out_path = self.config.work_dir.join(format!("out-{stamp}.mp4"));

        let mut req = self.client.get(format!("{ostore_url}/api/files/{src_key}"));
        if let Some(tok) = &self.config.ostore_token {
            req = req.bearer_auth(tok);
        }
        let resp = req
            .send()
            .await
            .map_err(|err| MeshError::Upstream(format!("ostore download failed: {err}")))?;
        if !resp.status().is_success() {
            return Err(MeshError::NotFound(format!(
                "ostore object {src_key} not found"
            )));
        }

        let mut file = fs::File::create(&in_path)
            .await
            .map_err(|err| MeshError::Internal(format!("create temp input failed: {err}")))?;
        let mut stream = resp.bytes_stream();
        while let Some(chunk) = stream.next().await {
            let data = chunk
                .map_err(|err| MeshError::Upstream(format!("ostore stream read failed: {err}")))?;
            file.write_all(&data)
                .await
                .map_err(|err| MeshError::Internal(format!("write temp input failed: {err}")))?;
        }
        file.flush()
            .await
            .map_err(|err| MeshError::Internal(format!("flush temp input failed: {err}")))?;
        drop(file);

        let remux_res = run_ffmpeg_faststart(&in_path, &out_path).await;
        let _ = fs::remove_file(&in_path).await;
        remux_res?;

        let up_res = self
            .upload_file_to_ostore(ostore_url, dst_key, &out_path)
            .await;
        let _ = fs::remove_file(&out_path).await;
        up_res?;

        Ok(format!("faststart uploaded to ostore:{dst_key}"))
    }

    async fn upload_file_to_ostore(
        &self,
        ostore_url: &str,
        dest_key: &str,
        file_path: &Path,
    ) -> Result<(), MeshError> {
        let file = fs::File::open(file_path)
            .await
            .map_err(|err| MeshError::Internal(format!("open remuxed file failed: {err}")))?;
        let meta = file
            .metadata()
            .await
            .map_err(|err| MeshError::Internal(format!("stat remuxed file failed: {err}")))?;
        let stream = ReaderStream::with_capacity(file, 65_536);
        let body = reqwest::Body::wrap_stream(stream);

        let mut req = self
            .client
            .put(format!("{ostore_url}/api/files/{dest_key}"))
            .header("content-length", meta.len())
            .header("content-type", "video/mp4")
            .body(body);
        if let Some(tok) = &self.config.ostore_token {
            req = req.bearer_auth(tok);
        }
        let resp = req
            .send()
            .await
            .map_err(|err| MeshError::Upstream(format!("ostore upload failed: {err}")))?;
        if !resp.status().is_success() {
            let status = resp.status();
            let text = resp.text().await.unwrap_or_default();
            return Err(MeshError::Upstream(format!(
                "ostore upload returned {status}: {text}"
            )));
        }
        Ok(())
    }
}

async fn run_ffmpeg_faststart(src: &PathBuf, dst: &PathBuf) -> Result<(), MeshError> {
    let output = Command::new("ffmpeg")
        .arg("-y")
        .arg("-hide_banner")
        .arg("-loglevel")
        .arg("error")
        .arg("-i")
        .arg(src)
        .arg("-c")
        .arg("copy")
        .arg("-movflags")
        .arg("+faststart")
        .arg(dst)
        .output()
        .await
        .map_err(|err| MeshError::Internal(format!("spawn ffmpeg failed: {err}")))?;

    if !output.status.success() {
        let stderr = String::from_utf8_lossy(&output.stderr);
        return Err(MeshError::Internal(format!(
            "ffmpeg faststart failed: {}",
            stderr.trim()
        )));
    }
    Ok(())
}

fn unix_now() -> u64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map_or(0, |d| d.as_secs())
}
