//! `BitTorrent` engine facade backed by `librqbit`.

use std::{
    collections::{HashMap, HashSet},
    fmt,
    io::SeekFrom,
    net::{Ipv4Addr, SocketAddr},
    ops::Range,
    path::PathBuf,
    sync::{Arc, RwLock},
    time::Duration,
};

use librqbit::{
    api::TorrentIdOrHash, AddTorrent, AddTorrentOptions, AddTorrentResponse, Api, ListenerOptions,
    ManagedTorrent, Session, SessionOptions, SessionPersistenceConfig, TorrentStatsState,
};
use serde::Serialize;
use tokio::{
    io::{AsyncRead, AsyncSeek, AsyncSeekExt},
    sync::Mutex,
};
use tracing::{debug, info, warn};

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

/// Whether `pause` should honor pin protection or force-pause a pinned torrent.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
#[non_exhaustive]
pub enum PauseMode {
    /// Keep pinned (liked) torrents downloading when a player closes or pauses.
    RespectPin,
    /// Explicitly pause even if the torrent is pinned (e.g. operator action in `CachePanel`).
    Force,
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
#[expect(
    clippy::struct_excessive_bools,
    reason = "JSON API DTO mirrors xstream TorrentStatus wire contract"
)]
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
    /// Piece segments `[start_pct, end_pct, state]` (`0=missing, 1=downloading, 2=cached`).
    pub piece_segments: Vec<(f64, f64, u8)>,
    /// Hash-check progress 0-100.
    pub check_progress: f64,
    /// True when pinned (protected from eviction, e.g. user-liked title).
    pub pinned: bool,
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

/// Number of fixed-width buckets reported in `piece_segments` for progress/cache heatmaps.
const PIECE_SEGMENT_BUCKETS: usize = 64;

/// Minimum bytes downloaded before `head_ready` becomes true when piece bitmap is unavailable.
const HEAD_READY_MIN_BYTES: u64 = 1024 * 1024;

/// Maximum concurrent background (non-streaming) downloads allowed simultaneously.
const MAX_BACKGROUND_DOWNLOADS: usize = 2;

/// Core `BitTorrent` streaming engine wrapping a `librqbit::Session`.
pub struct BtEngine {
    session: Arc<Session>,
    api: Api,
    cache_dir: PathBuf,
    policy: EvictionPolicy,
    tracker: CacheTracker,
    seek_cursors: Mutex<HashMap<String, Box<dyn AsyncVideoStream>>>,
    active_offsets: RwLock<HashMap<String, u64>>,
    yielded_for_playback: Mutex<HashSet<String>>,
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
    piece_range: Range<u32>,
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

        let api = Api::new(Arc::clone(&session), None);

        Ok(Self {
            session,
            api,
            cache_dir: config.cache_dir.clone(),
            policy,
            tracker,
            seek_cursors: Mutex::new(HashMap::new()),
            active_offsets: RwLock::new(HashMap::new()),
            yielded_for_playback: Mutex::new(HashSet::new()),
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
            let st = self.build_status(&hash, &existing);
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

        self.schedule_restrict_to_video_file(Arc::clone(&handle))
            .await;
        let st = self.build_status(&hash, &handle);

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
        Ok(self.build_status(&hash, &handle))
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

        let st = self.build_status(&hash, &handle);
        Ok(StreamCheckDto {
            hash,
            cached: st.cached,
            head_ready: st.head_ready,
            path: st.video_file.unwrap_or_default(),
            size: st.video_size,
            mime: st.mime,
        })
    }

    /// Pause a managed torrent (respects pin protection unless `PauseMode::Force`).
    ///
    /// # Errors
    /// Returns [`BtError::NotFound`] or [`BtError::Internal`].
    pub async fn pause(&self, raw_hash: &str, mode: PauseMode) -> Result<(), BtError> {
        let (hash, handle) = self.lookup_handle(raw_hash)?;
        {
            let mut cursors = self.seek_cursors.lock().await;
            cursors.remove(&hash);
        }
        if let Ok(mut offsets) = self.active_offsets.write() {
            offsets.remove(&hash);
        }
        if matches!(mode, PauseMode::Force) {
            let mut yielded = self.yielded_for_playback.lock().await;
            yielded.remove(&hash);
        }
        if matches!(mode, PauseMode::RespectPin) && self.tracker.is_pinned(&hash) {
            debug!(hash = %hash, "skipping pause for pinned (liked) torrent");
            return Ok(());
        }
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

    /// Shift piece prioritization to the byte offset corresponding to `time_sec / duration_sec`.
    ///
    /// Maintains a single prewarm `FileStream` per torrent so rapid scrubbing immediately
    /// replaces any previous seek window and focuses peer bandwidth on the new offset.
    ///
    /// # Errors
    /// Returns [`BtError::InvalidInput`], [`BtError::NotFound`], or [`BtError::NotReady`].
    pub async fn seek(
        &self,
        raw_hash: &str,
        time_sec: f64,
        duration_sec: f64,
    ) -> Result<(), BtError> {
        let (hash, handle) = self.lookup_handle(raw_hash)?;
        self.tracker.touch(&hash);

        let Some(video) = pick_video_from_handle(&handle) else {
            return Ok(());
        };
        self.restrict_to_video_file(&handle).await;

        let stats = handle.stats();
        if matches!(stats.state, TorrentStatsState::Paused) {
            let _ = self.session.unpause(&handle).await;
        }

        let target_byte = byte_offset_for_time(time_sec, duration_sec, video.len);
        if let Ok(mut offsets) = self.active_offsets.write() {
            offsets.insert(hash.clone(), target_byte);
        }

        if stats.finished {
            return Ok(());
        }

        let mut stream = Arc::clone(&handle)
            .stream(video.id)
            .await
            .map_err(|err| BtError::NotReady(format!("seek stream unavailable: {err}")))?;
        stream
            .seek(SeekFrom::Start(target_byte))
            .await
            .map_err(|err| BtError::Internal(format!("seek stream failed: {err}")))?;

        let mut cursors = self.seek_cursors.lock().await;
        cursors.insert(hash.clone(), Box::new(stream));
        debug!(hash = %hash, target_byte, "seek prewarm cursor updated");
        Ok(())
    }

    /// Record the latest playback position for heatmap highlighting without opening a stream.
    pub fn note_playback_progress(&self, raw_hash: &str, time_sec: f64, duration_sec: f64) {
        let Ok((hash, handle)) = self.lookup_handle(raw_hash) else {
            return;
        };
        self.tracker.touch(&hash);
        let Some(video) = pick_video_from_handle(&handle) else {
            return;
        };
        let offset = byte_offset_for_time(time_sec, duration_sec, video.len);
        if let Ok(mut offsets) = self.active_offsets.write() {
            offsets.insert(hash, offset);
        }
    }

    /// Record an active HTTP Range stream offset and release any redundant seek prewarm cursor.
    pub async fn note_stream_offset(&self, raw_hash: &str, offset_bytes: u64) {
        let Some(hash) = normalize_hash(raw_hash) else {
            return;
        };
        self.tracker.touch(&hash);
        if let Ok(mut offsets) = self.active_offsets.write() {
            offsets.insert(hash.clone(), offset_bytes);
        }
        let mut cursors = self.seek_cursors.lock().await;
        cursors.remove(&hash);
    }

    /// Delete a torrent from the session, optionally removing downloaded files.
    ///
    /// # Errors
    /// Returns [`BtError::InvalidInput`] or [`BtError::Internal`].
    pub async fn remove(&self, raw_hash: &str, delete_files: DeleteFiles) -> Result<(), BtError> {
        let hash = normalize_hash(raw_hash)
            .ok_or_else(|| BtError::InvalidInput("invalid info-hash".to_string()))?;
        let id = parse_torrent_id(&hash)?;
        {
            let mut cursors = self.seek_cursors.lock().await;
            cursors.remove(&hash);
        }
        if let Ok(mut offsets) = self.active_offsets.write() {
            offsets.remove(&hash);
        }
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
                let st = self.build_status(&h, handle);
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
            self.enforce_background_limits(total_disk).await;
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

        self.enforce_background_limits(used_after).await;

        EvictResultDto {
            evicted_hashes,
            freed_bytes: total_disk.saturating_sub(used_after),
            used_bytes: used_after,
            max_bytes: self.policy.max_bytes,
        }
    }

    /// Enforce disk watermark brake and concurrency cap for non-streaming background downloads.
    ///
    /// Never pauses a torrent that has an active `/stream` connection, but WILL pause
    /// background (including pinned/liked) downloads once disk usage hits the 85% target
    /// watermark or exceeds [`MAX_BACKGROUND_DOWNLOADS`], preventing pinned downloads from
    /// exhausting host disk space or starving playback.
    async fn enforce_background_limits(&self, used_bytes: u64) {
        let over_watermark = self.policy.max_bytes > 0 && used_bytes >= self.policy.target_bytes;
        let has_foreground_playback = self.tracker.total_active_streams() > 0;

        let mut live_bg: Vec<(String, u64, Arc<ManagedTorrent>)> =
            self.session.with_torrents(|iter| {
                iter.filter_map(|(_, handle)| {
                    let stats = handle.stats();
                    if stats.finished || !matches!(stats.state, TorrentStatsState::Live) {
                        return None;
                    }
                    let h = handle.info_hash().as_string();
                    if self.tracker.active_streams_for(&h) > 0 {
                        return None;
                    }
                    Some((h, stats.progress_bytes, Arc::clone(handle)))
                })
                .collect()
            });

        if live_bg.is_empty() {
            return;
        }

        if over_watermark {
            for (h, _, handle) in &live_bg {
                if self.session.pause(handle).await.is_ok() {
                    warn!(
                        hash = %h,
                        used_bytes,
                        target_bytes = self.policy.target_bytes,
                        "paused background download: disk watermark reached"
                    );
                }
            }
            return;
        }

        if has_foreground_playback {
            let mut yielded = self.yielded_for_playback.lock().await;
            for (h, _, handle) in &live_bg {
                if self.session.pause(handle).await.is_ok() {
                    yielded.insert(h.clone());
                }
            }
            return;
        }

        if live_bg.len() > MAX_BACKGROUND_DOWNLOADS {
            // Keep the highest-progress torrents running so they complete fastest; pause the rest.
            live_bg.sort_by_key(|a| std::cmp::Reverse(a.1));
            let mut yielded = self.yielded_for_playback.lock().await;
            for (h, _, handle) in live_bg.iter().skip(MAX_BACKGROUND_DOWNLOADS) {
                if self.session.pause(handle).await.is_ok() {
                    yielded.insert(h.clone());
                    info!(
                        hash = %h,
                        max_bg = MAX_BACKGROUND_DOWNLOADS,
                        "paused excess background download to cap concurrency"
                    );
                }
            }
        }
    }

    /// Yield (pause) all non-streaming background downloads so `foreground_hash` gets 100% bandwidth.
    async fn yield_background_downloads(&self, foreground_hash: &str) {
        let to_yield: Vec<(String, Arc<ManagedTorrent>)> = self.session.with_torrents(|iter| {
            iter.filter_map(|(_, handle)| {
                let h = handle.info_hash().as_string();
                if h == foreground_hash || self.tracker.active_streams_for(&h) > 0 {
                    return None;
                }
                let stats = handle.stats();
                if stats.finished || !matches!(stats.state, TorrentStatsState::Live) {
                    return None;
                }
                Some((h, Arc::clone(handle)))
            })
            .collect()
        });

        if to_yield.is_empty() {
            return;
        }

        let mut yielded = self.yielded_for_playback.lock().await;
        for (h, handle) in to_yield {
            if self.session.pause(&handle).await.is_ok() {
                yielded.insert(h.clone());
                debug!(hash = %h, foreground = %foreground_hash, "yielded background download for playback");
            }
        }
    }

    /// Resume previously yielded background downloads once no playback stream is active
    /// and disk usage is below the 85% watermark.
    pub async fn restore_yielded_if_idle(&self) {
        if self.tracker.total_active_streams() > 0 {
            return;
        }
        let candidates: Vec<String> = {
            let yielded = self.yielded_for_playback.lock().await;
            if yielded.is_empty() {
                return;
            }
            yielded.iter().cloned().collect()
        };

        let cache_dir = self.cache_dir.clone();
        let used = tokio::task::spawn_blocking(move || disk_usage_bytes(&cache_dir))
            .await
            .unwrap_or(0);
        if self.policy.max_bytes > 0 && used >= self.policy.target_bytes {
            return;
        }

        let currently_live = self.session.with_torrents(|iter| {
            iter.filter(|(_, h)| {
                let st = h.stats();
                !st.finished && matches!(st.state, TorrentStatsState::Live)
            })
            .count()
        });
        let slots = MAX_BACKGROUND_DOWNLOADS.saturating_sub(currently_live);
        if slots == 0 {
            return;
        }

        let mut resumed = 0usize;
        let mut to_remove = Vec::new();
        for h in candidates {
            if resumed >= slots {
                break;
            }
            let Ok(id) = parse_torrent_id(&h) else {
                to_remove.push(h);
                continue;
            };
            let Some(handle) = self.session.get(id) else {
                to_remove.push(h);
                continue;
            };
            if handle.stats().finished {
                to_remove.push(h);
                continue;
            }
            if self.session.unpause(&handle).await.is_ok() {
                resumed += 1;
                to_remove.push(h.clone());
                debug!(hash = %h, "resumed yielded background download");
            }
        }

        if !to_remove.is_empty() {
            let mut yielded = self.yielded_for_playback.lock().await;
            for h in to_remove {
                yielded.remove(&h);
            }
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
        self.yield_background_downloads(&hash).await;
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

    async fn restrict_to_video_file(&self, handle: &Arc<ManagedTorrent>) -> bool {
        let Some(video) = pick_video_from_handle(handle) else {
            return false;
        };
        if let Some(current) = handle.only_files() {
            if current.len() == 1 && current[0] == video.id {
                return true;
            }
        }
        let mut only = HashSet::with_capacity(1);
        only.insert(video.id);
        match self.session.update_only_files(handle, &only).await {
            Ok(()) => true,
            Err(err) => {
                debug!(
                    file_id = video.id,
                    error = %err,
                    "deferring only_files restriction (torrent still initializing)"
                );
                false
            }
        }
    }

    async fn schedule_restrict_to_video_file(&self, handle: Arc<ManagedTorrent>) {
        if self.restrict_to_video_file(&handle).await {
            return;
        }
        let session = Arc::clone(&self.session);
        tokio::spawn(async move {
            for _ in 0..12 {
                tokio::time::sleep(Duration::from_millis(500)).await;
                let Some(video) = pick_video_from_handle(&handle) else {
                    continue;
                };
                if let Some(current) = handle.only_files() {
                    if current.len() == 1 && current[0] == video.id {
                        return;
                    }
                }
                let mut only = HashSet::with_capacity(1);
                only.insert(video.id);
                if session.update_only_files(&handle, &only).await.is_ok() {
                    debug!(file_id = video.id, "restricted torrent only_files to video");
                    return;
                }
            }
        });
    }

    fn build_status(&self, hash: &str, handle: &ManagedTorrent) -> TorrentStatusDto {
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

        let (video_file, video_size, local_size, mime, ready, piece_range) = match video {
            Some(v) => {
                let file_done = stats.file_progress.get(v.id).copied().unwrap_or(0);
                (
                    Some(v.rel_path),
                    v.len,
                    file_done,
                    v.mime,
                    v.len > 0,
                    Some(v.piece_range),
                )
            }
            None => (
                None,
                stats.total_bytes,
                stats.progress_bytes,
                "video/mp4",
                false,
                None,
            ),
        };

        let progress = compute_percent(local_size, video_size);
        let state_label = map_state(&stats);
        let is_active_download = state_label == "downloading";

        let active_ratio = if is_active_download && video_size > 0 {
            self.active_offsets
                .read()
                .ok()
                .and_then(|map| map.get(hash).copied())
                .map(|off| compute_percent(off, video_size) / 100.0)
        } else {
            None
        };

        let (piece_segments, first_piece_have) = match piece_range {
            Some(range) if !range.is_empty() => {
                if stats.finished {
                    let count = usize::try_from(range.end.saturating_sub(range.start)).unwrap_or(0);
                    let all_have = vec![true; count.clamp(1, PIECE_SEGMENT_BUCKETS)];
                    (
                        compute_piece_segments(&all_have, None, PIECE_SEGMENT_BUCKETS),
                        true,
                    )
                } else if let Ok(id) = parse_torrent_id(hash) {
                    if let Ok((bf, total_pieces)) = self.api.api_dump_haves(id) {
                        let start = usize::try_from(range.start).unwrap_or(0);
                        let end = usize::try_from(range.end.min(total_pieces)).unwrap_or(start);
                        let mut bits = Vec::with_capacity(end.saturating_sub(start));
                        for idx in start..end {
                            bits.push(bf.get(idx).as_deref().copied().unwrap_or(false));
                        }
                        let first_ok = bits.first().copied().unwrap_or(false);
                        let segs =
                            compute_piece_segments(&bits, active_ratio, PIECE_SEGMENT_BUCKETS);
                        (segs, first_ok)
                    } else {
                        (Vec::new(), false)
                    }
                } else {
                    (Vec::new(), false)
                }
            }
            _ => (Vec::new(), false),
        };

        let head_ready =
            ready && (stats.finished || first_piece_have || local_size >= HEAD_READY_MIN_BYTES);

        TorrentStatusDto {
            hash: hash.to_string(),
            name,
            ready,
            cached: local_size > HEAD_READY_MIN_BYTES,
            head_ready,
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
            piece_segments,
            check_progress: 0.0,
            pinned: self.tracker.is_pinned(hash),
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

            select_video_file(&candidates).and_then(|picked| {
                let fi = meta.file_infos.get(picked.id)?;
                Some(VideoFileInfo {
                    id: picked.id,
                    rel_path: picked.path.to_string_lossy().into_owned(),
                    len: picked.len,
                    mime: mime_for_path(picked.path),
                    piece_range: fi.piece_range.clone(),
                })
            })
        })
        .ok()
        .flatten()
}

/// Convert a `(time_sec, duration_sec)` playback position into a clamped byte offset.
fn byte_offset_for_time(time_sec: f64, duration_sec: f64, total_bytes: u64) -> u64 {
    if total_bytes == 0 || !time_sec.is_finite() || !duration_sec.is_finite() || duration_sec <= 0.0
    {
        return 0;
    }
    let ratio = (time_sec / duration_sec).clamp(0.0, 0.995);
    // Scale via integer basis points (0..=10_000) without `as` casts.
    let mut bp: u64 = 0;
    for step in (0..=10_000_u32).rev() {
        if f64::from(step) / 10_000.0 <= ratio {
            bp = u64::from(step);
            break;
        }
    }
    let scaled = u128::from(total_bytes)
        .saturating_mul(u128::from(bp))
        .checked_div(10_000)
        .unwrap_or(0);
    u64::try_from(scaled).unwrap_or(total_bytes.saturating_sub(1))
}

/// Compress per-piece download booleans into fixed-width `[start_pct, end_pct, state]` buckets.
///
/// States match xstream's `PlayerProgressBar` and `CachePanel` contract:
/// `0 = missing`, `1 = downloading / partial`, `2 = cached`.
pub fn compute_piece_segments(
    have_bits: &[bool],
    active_ratio: Option<f64>,
    max_buckets: usize,
) -> Vec<(f64, f64, u8)> {
    let total = have_bits.len();
    if total == 0 || max_buckets == 0 {
        return Vec::new();
    }
    let buckets = total.min(max_buckets);
    let buckets_u32 = u32::try_from(buckets).unwrap_or(1);
    let active_bucket = active_ratio.and_then(|r| {
        if !r.is_finite() {
            return None;
        }
        let clamped = r.clamp(0.0, 0.9999);
        for b in (0..buckets_u32).rev() {
            if f64::from(b) / f64::from(buckets_u32) <= clamped {
                return usize::try_from(b).ok();
            }
        }
        Some(0)
    });

    let mut out = Vec::with_capacity(buckets);
    for b in 0..buckets {
        let start_idx = b.saturating_mul(total) / buckets;
        let end_idx = ((b + 1).saturating_mul(total) / buckets)
            .max(start_idx + 1)
            .min(total);
        let slice = &have_bits[start_idx..end_idx];
        let have_count = slice.iter().filter(|&&h| h).count();

        let state = if have_count == slice.len() {
            2_u8
        } else {
            u8::from(have_count > 0 || active_bucket == Some(b))
        };

        let start_u32 = u32::try_from(b).unwrap_or(0);
        let end_u32 = u32::try_from(b + 1).unwrap_or(buckets_u32);
        let start_pct = (f64::from(start_u32) * 1000.0 / f64::from(buckets_u32)).round() / 10.0;
        let end_pct = (f64::from(end_u32) * 1000.0 / f64::from(buckets_u32)).round() / 10.0;
        out.push((start_pct, end_pct, state));
    }
    out
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

    #[test]
    fn piece_segments_maps_cached_partial_and_active_cursor() {
        let mut bits = vec![false; 128];
        // First 32 pieces cached -> first 16 buckets (of 64) are cached (2).
        for b in bits.iter_mut().take(32) {
            *b = true;
        }
        // One piece in bucket 16 cached -> partial (1).
        bits[32] = true;

        let segs = compute_piece_segments(&bits, Some(0.5), 64);
        assert_eq!(segs.len(), 64);
        assert_eq!(segs[0].2, 2);
        assert_eq!(segs[15].2, 2);
        assert_eq!(segs[16].2, 1);
        assert_eq!(segs[17].2, 0);
        // Active cursor at 50% (bucket 32) highlighted as downloading (1).
        assert_eq!(segs[32].2, 1);
        assert_eq!(segs[63].2, 0);
    }

    #[test]
    fn byte_offset_clamps_bounds() {
        assert_eq!(byte_offset_for_time(0.0, 100.0, 10_000), 0);
        assert_eq!(byte_offset_for_time(50.0, 100.0, 10_000), 5_000);
        assert_eq!(byte_offset_for_time(200.0, 100.0, 10_000), 9_950);
        assert_eq!(byte_offset_for_time(10.0, 0.0, 10_000), 0);
    }
}
