//! `BitTorrent` engine facade backed by `librqbit`.

use std::{
    collections::HashSet,
    fmt,
    net::{Ipv4Addr, SocketAddr},
    path::PathBuf,
    sync::Arc,
};

use librqbit::{
    api::TorrentIdOrHash, AddTorrent, AddTorrentOptions, AddTorrentResponse, ListenerOptions,
    ManagedTorrent, Session, SessionOptions, SessionPersistenceConfig, TorrentStatsState,
};
use serde::Serialize;
use tokio::io::{AsyncRead, AsyncSeek};
use tracing::{info, warn};

use crate::{
    cache::{
        disk_usage_bytes, format_bytes, plan_eviction, unix_now_secs, ActiveStreamGuard,
        CacheEntry, CacheTracker, EvictionPolicy,
    },
    config::Config,
    error::BtError,
    video::{extract_info_hash, mime_for_path, normalize_hash, select_video_file, FileCandidate},
};

/// Whether a newly added torrent starts paused or actively downloading.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
#[non_exhaustive]
pub enum StartMode {
    /// Start paused until playback or an explicit resume occurs.
    Paused,
    /// Start active immediately (e.g. when the user clicks play).
    Active,
}

/// Whether deleting a torrent also removes its downloaded files from disk.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
#[non_exhaustive]
pub enum DeleteFiles {
    /// Keep files on disk.
    Keep,
    /// Remove files from disk.
    Remove,
}

/// Result returned when adding a magnet link.
#[derive(Debug, Clone, Serialize)]
pub struct AddOutcome {
    /// Lowercase 40-char hex info-hash.
    pub hash: String,
    /// Always `"added"` for API compatibility.
    pub status: &'static str,
    /// Whether torrent metadata is resolved and the primary video file is known.
    pub ready: bool,
    /// Number of currently connected live peers.
    pub peers: u32,
    /// Overall download progress in `[0.0, 100.0]`.
    pub progress: f64,
}

/// Response payload matching xstream's `/api/check/{hash}` contract.
#[derive(Debug, Clone, Serialize)]
pub struct StreamCheckDto {
    /// Lowercase 40-char hex info-hash.
    pub hash: String,
    /// True if at least 1 MiB of the video has been downloaded.
    pub cached: bool,
    /// True when metadata is resolved and `GET /stream/{hash}` can serve bytes on demand.
    pub head_ready: bool,
    /// Relative path of the selected video file inside the torrent.
    pub path: String,
    /// Total size of the selected video file in bytes.
    pub size: u64,
    /// HTTP `Content-Type` MIME string for the video file.
    pub mime: &'static str,
}

/// Response payload matching xstream's `/torrent/status/{hash}` contract.
#[derive(Debug, Clone, Serialize)]
pub struct TorrentStatusDto {
    /// Lowercase 40-char hex info-hash.
    pub hash: String,
    /// Torrent display name.
    pub name: Option<String>,
    /// True when metadata is resolved and a playable video file was found.
    pub ready: bool,
    /// True when at least 1 MiB has been downloaded.
    pub cached: bool,
    /// True when ready to stream on demand via `FileStream`.
    pub head_ready: bool,
    /// Connected live peers.
    pub peers: u32,
    /// Download progress percentage `[0.0, 100.0]`.
    pub progress: f64,
    /// Current download rate in bytes/sec.
    pub download_rate: u64,
    /// Current upload rate in bytes/sec.
    pub upload_rate: u64,
    /// Relative path of the selected video file.
    pub video_file: Option<String>,
    /// Total size of the selected video file in bytes.
    pub video_size: u64,
    /// Downloaded bytes of the selected video file.
    pub local_size: u64,
    /// HTTP `Content-Type` MIME string.
    pub mime: &'static str,
    /// Human-readable engine state (`"initializing"`, `"downloading"`, `"paused"`, `"finished"`, `"error"`).
    pub state: &'static str,
    /// Verified pieces count.
    pub verified_pieces: u64,
    /// Quality label (reserved for compatibility).
    pub quality: &'static str,
    /// Piece segments (empty for `librqbit` streaming mode).
    pub piece_segments: Vec<(u32, u32, u8)>,
    /// Hash-check progress 0-100.
    pub check_progress: f64,
}

/// Object-safe trait combining `AsyncRead + AsyncSeek + Send + Unpin` for video streams.
pub trait AsyncVideoStream: AsyncRead + AsyncSeek + Send + Unpin {}

impl<T: AsyncRead + AsyncSeek + Send + Unpin> AsyncVideoStream for T {}

/// An open async-readable, async-seekable video stream handle.
pub struct OpenVideoStream {
    /// Underlying async stream (backed by `librqbit` `FileStream`).
    pub stream: Box<dyn AsyncVideoStream>,
    /// Total length of the video file in bytes.
    pub total_size: u64,
    /// HTTP MIME type for `Content-Type`.
    pub mime: &'static str,
    /// RAII guard preventing eviction while this stream is active.
    pub guard: ActiveStreamGuard,
}

/// Summary metrics matching xstream's `/api/cache/metrics` contract.
#[derive(Debug, Clone, Serialize)]
pub struct CacheMetricsDto {
    /// Total cached torrents with known video metadata.
    pub total: usize,
    /// Count of completed torrents (`progress >= 99.9`).
    pub completed: usize,
    /// Count of incomplete torrents.
    pub downloading: usize,
    /// Measured allocated disk bytes (`st_blocks * 512`).
    pub used_bytes: u64,
    /// Human-readable disk usage string.
    pub used_human: String,
    /// Configured disk quota in bytes.
    pub max_bytes: u64,
    /// Human-readable disk quota string.
    pub max_human: String,
}

/// Listing payload matching xstream's `/api/cache` contract.
#[derive(Debug, Clone, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct CacheListDto {
    /// Measured allocated disk bytes (`st_blocks * 512`).
    pub total_size: u64,
    /// Configured disk quota in bytes.
    pub max_size: u64,
    /// Number of items in `items`.
    pub item_count: usize,
    /// Per-torrent status entries.
    pub items: Vec<TorrentStatusDto>,
}

/// Result of a quota enforcement sweep.
#[derive(Debug, Clone, Serialize)]
pub struct EvictResultDto {
    /// Hashes evicted during this sweep.
    pub evicted_hashes: Vec<String>,
    /// Approximate bytes freed.
    pub freed_bytes: u64,
    /// Disk usage measured after eviction.
    pub used_bytes: u64,
    /// Configured disk quota in bytes.
    pub max_bytes: u64,
}

impl fmt::Debug for OpenVideoStream {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.debug_struct("OpenVideoStream")
            .field("total_size", &self.total_size)
            .field("mime", &self.mime)
            .finish_non_exhaustive()
    }
}

/// Core `BitTorrent` streaming engine wrapping a `librqbit::Session`.
pub struct BtEngine {
    session: Arc<Session>,
    cache_dir: PathBuf,
    policy: EvictionPolicy,
    tracker: CacheTracker,
}

impl fmt::Debug for BtEngine {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.debug_struct("BtEngine")
            .field("torrent_count", &self.torrent_count())
            .finish()
    }
}

struct VideoFileInfo {
    id: usize,
    rel_path: String,
    len: u64,
    mime: &'static str,
}

impl BtEngine {
    /// Initialize a `librqbit::Session` using the provided [`Config`].
    ///
    /// # Errors
    /// Returns [`BtError::Internal`] if the cache directory cannot be created
    /// or `librqbit::Session` fails to initialize.
    pub async fn new(config: &Config) -> Result<Self, BtError> {
        tokio::fs::create_dir_all(&config.cache_dir)
            .await
            .map_err(|err| BtError::Internal(format!("create cache dir failed: {err}")))?;

        let state_dir = config.cache_dir.join(".rqbit-state");
        tokio::fs::create_dir_all(&state_dir)
            .await
            .map_err(|err| BtError::Internal(format!("create state dir failed: {err}")))?;

        let opts = SessionOptions {
            fastresume: true,
            persistence: Some(SessionPersistenceConfig::Json {
                folder: Some(state_dir),
            }),
            listen: Some(ListenerOptions {
                listen_addr: SocketAddr::from((Ipv4Addr::UNSPECIFIED, config.bt_listen_port)),
                ..ListenerOptions::default()
            }),
            ..SessionOptions::default()
        };

        let session = Session::new_with_opts(config.cache_dir.clone(), opts)
            .await
            .map_err(|err| BtError::Internal(format!("librqbit session init failed: {err}")))?;

        let policy = EvictionPolicy::from_max_bytes(config.max_cache_bytes);
        let tracker = CacheTracker::new();

        // Seed LRU timestamps for any persisted torrents restored by librqbit.
        session.with_torrents(|iter| {
            for (_, handle) in iter {
                let h = handle.info_hash().as_string();
                tracker.touch(&h);
            }
        });

        info!(
            cache_dir = %config.cache_dir.display(),
            listen_port = config.bt_listen_port,
            max_cache_bytes = config.max_cache_bytes,
            "librqbit session initialized"
        );

        Ok(Self {
            session,
            cache_dir: config.cache_dir.clone(),
            policy,
            tracker,
        })
    }

    /// Number of torrents currently managed by the session.
    pub fn torrent_count(&self) -> usize {
        self.session.with_torrents(|iter| iter.count())
    }

    /// Add a magnet URI (or bare 40-char hash) to the session.
    ///
    /// Idempotent: if the info-hash is already managed, returns its current status.
    ///
    /// # Errors
    /// Returns [`BtError::InvalidInput`] if `magnet` does not contain a valid info-hash,
    /// or [`BtError::Internal`] if `librqbit` fails to add the torrent.
    pub async fn add_magnet(&self, magnet: &str, mode: StartMode) -> Result<AddOutcome, BtError> {
        let hash = extract_info_hash(magnet)
            .ok_or_else(|| BtError::InvalidInput("invalid magnet or info-hash".to_string()))?;
        self.tracker.touch(&hash);
        let id = parse_torrent_id(&hash)?;

        if let Some(existing) = self.session.get(id) {
            if matches!(mode, StartMode::Active) {
                let _ = self.session.unpause(&existing).await;
            }
            self.restrict_to_video_file(&existing).await;
            let st = build_status(&hash, &existing);
            return Ok(AddOutcome {
                hash,
                status: "added",
                ready: st.ready,
                peers: st.peers,
                progress: st.progress,
            });
        }

        let opts = AddTorrentOptions {
            paused: matches!(mode, StartMode::Paused),
            overwrite: true,
            ..AddTorrentOptions::default()
        };

        let resp = self
            .session
            .add_torrent(AddTorrent::from_url(magnet), Some(opts))
            .await
            .map_err(|err| BtError::Internal(format!("add_torrent failed: {err}")))?;

        let handle = match resp {
            AddTorrentResponse::Added(_, h) | AddTorrentResponse::AlreadyManaged(_, h) => h,
            AddTorrentResponse::ListOnly(_) => {
                return Err(BtError::Internal(
                    "unexpected list_only response from add_torrent".to_string(),
                ));
            }
        };

        self.restrict_to_video_file(&handle).await;
        let st = build_status(&hash, &handle);

        info!(
            hash = %hash,
            ready = st.ready,
            peers = st.peers,
            "torrent added to librqbit"
        );

        Ok(AddOutcome {
            hash,
            status: "added",
            ready: st.ready,
            peers: st.peers,
            progress: st.progress,
        })
    }

    /// Return detailed status for a managed torrent.
    ///
    /// # Errors
    /// Returns [`BtError::InvalidInput`] for a malformed hash or [`BtError::NotFound`]
    /// if the torrent is not managed.
    pub fn status(&self, raw_hash: &str) -> Result<TorrentStatusDto, BtError> {
        let (hash, handle) = self.lookup_handle(raw_hash)?;
        Ok(build_status(&hash, &handle))
    }

    /// Return `/api/check/{hash}` readiness information.
    ///
    /// Unlike the legacy libtorrent engine, a torrent not yet in the session returns
    /// `head_ready: false` (HTTP 200) rather than 404 so frontend checks stay compatible.
    ///
    /// # Errors
    /// Returns [`BtError::InvalidInput`] if `raw_hash` is not a valid 40-char hex hash.
    pub fn check(&self, raw_hash: &str) -> Result<StreamCheckDto, BtError> {
        let hash = normalize_hash(raw_hash)
            .ok_or_else(|| BtError::InvalidInput("invalid info-hash".to_string()))?;
        let id = parse_torrent_id(&hash)?;

        let Some(handle) = self.session.get(id) else {
            return Ok(StreamCheckDto {
                hash,
                cached: false,
                head_ready: false,
                path: String::new(),
                size: 0,
                mime: "video/mp4",
            });
        };

        let st = build_status(&hash, &handle);
        Ok(StreamCheckDto {
            hash,
            cached: st.cached,
            head_ready: st.head_ready,
            path: st.video_file.unwrap_or_default(),
            size: st.video_size,
            mime: st.mime,
        })
    }

    /// Pause a managed torrent.
    ///
    /// # Errors
    /// Returns [`BtError::NotFound`] or [`BtError::Internal`].
    pub async fn pause(&self, raw_hash: &str) -> Result<(), BtError> {
        let (_, handle) = self.lookup_handle(raw_hash)?;
        self.session
            .pause(&handle)
            .await
            .map_err(|err| BtError::Internal(format!("pause failed: {err}")))
    }

    /// Resume (unpause) a managed torrent and restrict its download to the primary video file.
    ///
    /// # Errors
    /// Returns [`BtError::NotFound`] or [`BtError::Internal`].
    pub async fn resume(&self, raw_hash: &str) -> Result<(), BtError> {
        let (hash, handle) = self.lookup_handle(raw_hash)?;
        self.tracker.touch(&hash);
        self.restrict_to_video_file(&handle).await;
        self.session
            .unpause(&handle)
            .await
            .map_err(|err| BtError::Internal(format!("unpause failed: {err}")))
    }

    /// Delete a torrent from the session, optionally removing downloaded files.
    ///
    /// # Errors
    /// Returns [`BtError::InvalidInput`] or [`BtError::Internal`].
    pub async fn remove(&self, raw_hash: &str, delete_files: DeleteFiles) -> Result<(), BtError> {
        let hash = normalize_hash(raw_hash)
            .ok_or_else(|| BtError::InvalidInput("invalid info-hash".to_string()))?;
        let id = parse_torrent_id(&hash)?;
        let remove_disk = matches!(delete_files, DeleteFiles::Remove);
        self.session
            .delete(id, remove_disk)
            .await
            .map_err(|err| BtError::Internal(format!("delete failed: {err}")))?;
        self.tracker.forget(&hash);
        Ok(())
    }

    /// Pin a torrent hash so automatic quota eviction never deletes it (e.g. user-liked title).
    ///
    /// # Errors
    /// Returns [`BtError::InvalidInput`] if `raw_hash` is not a valid 40-char hex hash.
    pub fn pin(&self, raw_hash: &str) -> Result<(), BtError> {
        let hash = normalize_hash(raw_hash)
            .ok_or_else(|| BtError::InvalidInput("invalid info-hash".to_string()))?;
        self.tracker.pin(&hash);
        Ok(())
    }

    /// Remove pin protection from a torrent hash.
    ///
    /// # Errors
    /// Returns [`BtError::InvalidInput`] if `raw_hash` is not a valid 40-char hex hash.
    pub fn unpin(&self, raw_hash: &str) -> Result<(), BtError> {
        let hash = normalize_hash(raw_hash)
            .ok_or_else(|| BtError::InvalidInput("invalid info-hash".to_string()))?;
        self.tracker.unpin(&hash);
        Ok(())
    }

    /// List all cached torrents with known video metadata alongside real disk usage.
    pub async fn cache_list(&self) -> CacheListDto {
        let items: Vec<TorrentStatusDto> = self.session.with_torrents(|iter| {
            iter.filter_map(|(_, handle)| {
                let h = handle.info_hash().as_string();
                let st = build_status(&h, handle);
                (st.video_size > 0).then_some(st)
            })
            .collect()
        });
        let cache_dir = self.cache_dir.clone();
        let total_size = tokio::task::spawn_blocking(move || disk_usage_bytes(&cache_dir))
            .await
            .unwrap_or(0);
        CacheListDto {
            total_size,
            max_size: self.policy.max_bytes,
            item_count: items.len(),
            items,
        }
    }

    /// Return cache metrics summary matching xstream's `/api/cache/metrics` contract.
    pub async fn cache_metrics(&self) -> CacheMetricsDto {
        let list = self.cache_list().await;
        let completed = list.items.iter().filter(|i| i.progress >= 99.9).count();
        let total = list.items.len();
        CacheMetricsDto {
            total,
            completed,
            downloading: total.saturating_sub(completed),
            used_bytes: list.total_size,
            used_human: format_bytes(list.total_size),
            max_bytes: list.max_size,
            max_human: format_bytes(list.max_size),
        }
    }

    /// Enforce the configured disk cache quota using [`plan_eviction`].
    ///
    /// Measures real allocated disk blocks on disk (Invariant I1), plans deterministic
    /// LRU eviction respecting active streams and pins (Invariants I1-I5), and deletes
    /// evicted torrents including their on-disk payloads.
    pub async fn enforce_quota(&self) -> EvictResultDto {
        let cache_dir = self.cache_dir.clone();
        let total_disk = tokio::task::spawn_blocking(move || disk_usage_bytes(&cache_dir))
            .await
            .unwrap_or(0);

        if self.policy.max_bytes == 0 || total_disk <= self.policy.max_bytes {
            return EvictResultDto {
                evicted_hashes: Vec::new(),
                freed_bytes: 0,
                used_bytes: total_disk,
                max_bytes: self.policy.max_bytes,
            };
        }

        let entries: Vec<CacheEntry> = self.session.with_torrents(|iter| {
            iter.map(|(_, handle)| {
                let h = handle.info_hash().as_string();
                let stats = handle.stats();
                self.tracker.snapshot_entry(&h, stats.progress_bytes)
            })
            .collect()
        });

        let plan = plan_eviction(&entries, total_disk, self.policy, unix_now_secs());
        let mut evicted_hashes = Vec::with_capacity(plan.evict_hashes.len());

        for hash in &plan.evict_hashes {
            if let Ok(id) = parse_torrent_id(hash) {
                match self.session.delete(id, true).await {
                    Ok(()) => {
                        self.tracker.forget(hash);
                        evicted_hashes.push(hash.clone());
                        info!(hash = %hash, "evicted cached torrent to satisfy disk quota");
                    }
                    Err(err) => {
                        warn!(hash = %hash, error = %err, "failed to delete evicted torrent");
                    }
                }
            }
        }

        let cache_dir_after = self.cache_dir.clone();
        let used_after = tokio::task::spawn_blocking(move || disk_usage_bytes(&cache_dir_after))
            .await
            .unwrap_or(plan.remaining_bytes);

        EvictResultDto {
            evicted_hashes,
            freed_bytes: total_disk.saturating_sub(used_after),
            used_bytes: used_after,
            max_bytes: self.policy.max_bytes,
        }
    }

    /// Open a native async `FileStream` for the torrent's primary video file.
    ///
    /// Automatically unpauses the torrent and restricts `only_files` to the selected
    /// video file so streaming never wastes bandwidth on ads or sidecar files.
    ///
    /// # Errors
    /// Returns [`BtError::NotFound`] if the torrent is unknown, [`BtError::NotReady`]
    /// if metadata has not yet been resolved, or [`BtError::Internal`] if stream
    /// creation fails.
    pub async fn open_stream(&self, raw_hash: &str) -> Result<OpenVideoStream, BtError> {
        let (hash, handle) = self.lookup_handle(raw_hash)?;

        let Some(video) = pick_video_from_handle(&handle) else {
            // Ensure torrent is active so metadata resolution progresses.
            let _ = self.session.unpause(&handle).await;
            return Err(BtError::NotReady(format!(
                "metadata not yet resolved for {hash}"
            )));
        };

        self.restrict_to_video_file(&handle).await;

        let stats = handle.stats();
        if matches!(stats.state, TorrentStatsState::Paused) {
            if let Err(err) = self.session.unpause(&handle).await {
                warn!(hash = %hash, error = %err, "failed to unpause before stream");
            }
        }

        let guard = self.tracker.acquire_stream(&hash);
        let stream = Arc::clone(&handle)
            .stream(video.id)
            .await
            .map_err(|err| BtError::NotReady(format!("stream unavailable: {err}")))?;

        Ok(OpenVideoStream {
            stream: Box::new(stream),
            total_size: video.len,
            mime: video.mime,
            guard,
        })
    }

    fn lookup_handle(&self, raw_hash: &str) -> Result<(String, Arc<ManagedTorrent>), BtError> {
        let hash = normalize_hash(raw_hash)
            .ok_or_else(|| BtError::InvalidInput("invalid info-hash".to_string()))?;
        let id = parse_torrent_id(&hash)?;
        let handle = self
            .session
            .get(id)
            .ok_or_else(|| BtError::NotFound(hash.clone()))?;
        Ok((hash, handle))
    }

    async fn restrict_to_video_file(&self, handle: &Arc<ManagedTorrent>) {
        let Some(video) = pick_video_from_handle(handle) else {
            return;
        };
        if let Some(current) = handle.only_files() {
            if current.len() == 1 && current[0] == video.id {
                return;
            }
        }
        let mut only = HashSet::with_capacity(1);
        only.insert(video.id);
        if let Err(err) = self.session.update_only_files(handle, &only).await {
            warn!(
                file_id = video.id,
                error = %err,
                "failed to restrict torrent only_files to video"
            );
        }
    }
}

fn parse_torrent_id(hash: &str) -> Result<TorrentIdOrHash, BtError> {
    TorrentIdOrHash::parse(hash)
        .map_err(|err| BtError::InvalidInput(format!("invalid info-hash {hash}: {err}")))
}

fn pick_video_from_handle(handle: &ManagedTorrent) -> Option<VideoFileInfo> {
    handle
        .with_metadata(|meta| {
            let candidates: Vec<FileCandidate<'_>> = meta
                .file_infos
                .iter()
                .enumerate()
                .map(|(id, fi)| FileCandidate {
                    id,
                    path: fi.relative_filename.as_path(),
                    len: fi.len,
                })
                .collect();

            select_video_file(&candidates).map(|picked| VideoFileInfo {
                id: picked.id,
                rel_path: picked.path.to_string_lossy().into_owned(),
                len: picked.len,
                mime: mime_for_path(picked.path),
            })
        })
        .ok()
        .flatten()
}

fn build_status(hash: &str, handle: &ManagedTorrent) -> TorrentStatusDto {
    let stats = handle.stats();
    let video = pick_video_from_handle(handle);
    let name = handle.name();

    let (peers, download_rate, upload_rate, verified_pieces) = match &stats.live {
        Some(live) => (
            live.snapshot.peer_stats.live,
            live.download_speed.as_bytes(),
            live.upload_speed.as_bytes(),
            live.snapshot.downloaded_and_checked_pieces,
        ),
        None => (0, 0, 0, 0),
    };

    let (video_file, video_size, local_size, mime, ready) = match video {
        Some(v) => {
            let file_done = stats.file_progress.get(v.id).copied().unwrap_or(0);
            (Some(v.rel_path), v.len, file_done, v.mime, v.len > 0)
        }
        None => (
            None,
            stats.total_bytes,
            stats.progress_bytes,
            "video/mp4",
            false,
        ),
    };

    let progress = compute_percent(local_size, video_size);
    let state_label = map_state(&stats);

    TorrentStatusDto {
        hash: hash.to_string(),
        name,
        ready,
        cached: local_size > 1024 * 1024,
        head_ready: ready,
        peers,
        progress,
        download_rate,
        upload_rate,
        video_file,
        video_size,
        local_size,
        mime,
        state: state_label,
        verified_pieces,
        quality: "",
        piece_segments: Vec::new(),
        check_progress: 0.0,
    }
}

fn map_state(stats: &librqbit::TorrentStats) -> &'static str {
    if stats.finished {
        return "finished";
    }
    match stats.state {
        TorrentStatsState::Initializing { .. } => "initializing",
        TorrentStatsState::Live => "downloading",
        TorrentStatsState::Paused => "paused",
        TorrentStatsState::Error => "error",
    }
}

fn compute_percent(done: u64, total: u64) -> f64 {
    if total == 0 {
        return 0.0;
    }
    let clamped = done.min(total);
    // Avoid `as` casts (workspace lint `as_conversions`); scale via u128 permille.
    let permille = u128::from(clamped)
        .saturating_mul(10_000)
        .checked_div(u128::from(total))
        .unwrap_or(0);
    let permille_u32 = u32::try_from(permille).unwrap_or(10_000);
    f64::from(permille_u32) / 100.0
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn percent_handles_zero_and_bounds() {
        assert!(
            (compute_percent(0, 0) - 0.0).abs() < f64::EPSILON,
            "zero total"
        );
        assert!(
            (compute_percent(50, 100) - 50.0).abs() < f64::EPSILON,
            "half"
        );
        assert!(
            (compute_percent(150, 100) - 100.0).abs() < f64::EPSILON,
            "clamped"
        );
    }
}
