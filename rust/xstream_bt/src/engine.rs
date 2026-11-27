//! `BitTorrent` engine facade backed by `librqbit`.

use std::{
    collections::{HashMap, HashSet},
    fmt,
    io::{Read, SeekFrom},
    net::{Ipv6Addr, SocketAddr},
    ops::Range,
    path::{Path, PathBuf},
    sync::{Arc, RwLock},
    time::{Duration, Instant},
};

use librqbit::{
    api::TorrentIdOrHash, AddTorrent, AddTorrentOptions, AddTorrentResponse, Api,
    ConnectionOptions, ListenerMode, ListenerOptions, ManagedTorrent, PeerConnectionOptions,
    Session, SessionOptions, SessionPersistenceConfig, TorrentStatsState,
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
    mp4::{inspect_mp4_head, MoovLocation},
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

/// Minimum bytes downloaded before `cached` becomes true in status DTOs.
const CACHED_MIN_BYTES: u64 = 1024 * 1024;

/// Contiguous head bytes required from byte 0 before `head_ready` becomes true.
///
/// Covers `ftyp` + large FHD/4K MP4 `moov` atoms (commonly 8-9 MiB) plus initial keyframes
/// so the browser never stalls mid-`moov` and throws `MEDIA_ERR_SRC_NOT_SUPPORTED` (code=4).
pub const HEAD_READY_CONTIGUOUS_BYTES: u64 = 10 * 1024 * 1024;

/// Tail window prewarmed alongside head (covers tail-placed MP4 `moov` atoms & seek index).
const TAIL_PREWARM_BYTES: u64 = 4 * 1024 * 1024;

/// Maximum concurrent background (non-streaming) downloads allowed simultaneously.
const MAX_BACKGROUND_DOWNLOADS: usize = 2;

/// Head window cached for liked/background prewarm (~32 MiB via `FileStream` lookahead).
pub const PREWARM_HEAD_BYTES: u64 = 32 * 1024 * 1024;

/// Tail window cached for liked/background prewarm (MP4 moov atom & seek index).
pub const PREWARM_TAIL_BYTES: u64 = TAIL_PREWARM_BYTES;

/// Total byte cap for a single background prewarm before auto-pausing.
pub const PREWARM_MAX_BYTES: u64 = PREWARM_HEAD_BYTES + PREWARM_TAIL_BYTES;

/// Extra contiguous media bytes required past a fast-start `moov` box for immediate keyframe decode.
const FAST_START_KEYFRAME_BUFFER_BYTES: u64 = 2 * 1024 * 1024;

/// Maximum top-level MP4 header bytes read from disk to detect `moov` placement.
const MP4_HEAD_INSPECT_BYTES: usize = 64 * 1024;

/// High-availability public trackers injected alongside magnet trackers + DHT to speed up peer discovery.
const DEFAULT_PUBLIC_TRACKERS: &[&str] = &[
    "udp://tracker.opentrackr.org:1337/announce",
    "udp://open.stealth.si:80/announce",
    "udp://tracker.torrent.eu.org:451/announce",
    "udp://exodus.desync.com:6969/announce",
    "udp://tracker.moeking.me:6969/announce",
    "http://tracker.opentrackr.org:1337/announce",
];

/// Grace window (seconds) after the last `/stream`, `seek`, `progress`, or `resume` call
/// during which a torrent is treated as active foreground playback and must NOT be paused
/// by background maintenance between discrete browser HTTP Range requests.
const FOREGROUND_GRACE: Duration = Duration::from_secs(45);

type PrewarmCursorMap = HashMap<String, Vec<Box<dyn AsyncVideoStream>>>;

#[derive(Debug, Clone, Copy)]
struct PendingAddMode(StartMode);

struct PendingAdd {
    mode: PendingAddMode,
    abort: tokio::task::AbortHandle,
}

/// Core `BitTorrent` streaming engine wrapping a `librqbit::Session`.
pub struct BtEngine {
    session: Arc<Session>,
    api: Api,
    cache_dir: PathBuf,
    policy: EvictionPolicy,
    tracker: CacheTracker,
    seek_cursors: Mutex<HashMap<String, Box<dyn AsyncVideoStream>>>,
    prewarm_cursors: Arc<Mutex<PrewarmCursorMap>>,
    pending_adds: Arc<RwLock<HashMap<String, PendingAdd>>>,
    active_offsets: RwLock<HashMap<String, u64>>,
    last_foreground_at: RwLock<HashMap<String, Instant>>,
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
        let pins_file = state_dir.join("pins.json");

        let trackers: HashSet<url::Url> = DEFAULT_PUBLIC_TRACKERS
            .iter()
            .filter_map(|raw| url::Url::parse(raw).ok())
            .collect();

        let opts = SessionOptions {
            fastresume: true,
            persistence: Some(SessionPersistenceConfig::Json {
                folder: Some(state_dir),
            }),
            listen: Some(ListenerOptions {
                mode: ListenerMode::TcpAndUtp,
                listen_addr: SocketAddr::from((Ipv6Addr::UNSPECIFIED, config.bt_listen_port)),
                ipv4_only: false,
                ..ListenerOptions::default()
            }),
            connect: Some(ConnectionOptions {
                enable_tcp: true,
                peer_opts: Some(PeerConnectionOptions {
                    connect_timeout: Some(Duration::from_secs(4)),
                    read_write_timeout: Some(Duration::from_secs(10)),
                    keep_alive_interval: Some(Duration::from_secs(60)),
                    // Keep full 128-chunk (2 MiB) per-peer request window so high-RTT seedboxes
                    // are not BDP-capped to ~2.5 MB/s per peer.
                    max_request_window: Some(128),
                }),
                ..ConnectionOptions::default()
            }),
            trackers,
            peer_limit: Some(200),
            concurrent_init_limit: Some(8),
            ..SessionOptions::default()
        };

        let session = Session::new_with_opts(config.cache_dir.clone(), opts)
            .await
            .map_err(|err| BtError::Internal(format!("librqbit session init failed: {err}")))?;

        let policy = EvictionPolicy::from_max_bytes(config.max_cache_bytes);
        let tracker = CacheTracker::with_pins_file(pins_file);

        // Seed LRU timestamps and enforce on-demand mode (empty `only_files`) for any
        // persisted torrents restored by librqbit so background bulk downloads never run.
        let restored: Vec<Arc<ManagedTorrent>> = session.with_torrents(|iter| {
            iter.map(|(_, handle)| {
                let h = handle.info_hash().as_string();
                tracker.touch(&h);
                Arc::clone(handle)
            })
            .collect()
        });
        let empty_files = HashSet::new();
        for handle in &restored {
            if !matches!(handle.only_files().as_deref(), Some([])) {
                let _ = session.update_only_files(handle, &empty_files).await;
            }
        }

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
            prewarm_cursors: Arc::new(Mutex::new(HashMap::new())),
            pending_adds: Arc::new(RwLock::new(HashMap::new())),
            active_offsets: RwLock::new(HashMap::new()),
            last_foreground_at: RwLock::new(HashMap::new()),
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
            self.enforce_on_demand_mode(&existing).await;
            if matches!(mode, StartMode::Active) {
                self.mark_foreground(&hash);
                self.unpause_if_paused(&existing).await;
                self.ensure_head_prewarm(&hash, &existing).await;
            }
            let st = self.build_status(&hash, &existing);
            return Ok(AddOutcome {
                hash,
                status: "added",
                ready: st.ready,
                peers: st.peers,
                progress: st.progress,
            });
        }

        if let Ok(mut pending) = self.pending_adds.write() {
            if let Some(entry) = pending.get_mut(&hash) {
                if matches!(mode, StartMode::Active) {
                    entry.mode = PendingAddMode(StartMode::Active);
                    self.mark_foreground(&hash);
                }
                return Ok(AddOutcome {
                    hash,
                    status: "added",
                    ready: false,
                    peers: 0,
                    progress: 0.0,
                });
            }
        }

        if matches!(mode, StartMode::Active) {
            self.mark_foreground(&hash);
        }

        let rx = self.spawn_background_add(&hash, magnet, mode);

        if let Ok(Ok(res)) = tokio::time::timeout(Duration::from_millis(200), rx).await {
            res?;
            if let Some(handle) = self.session.get(id) {
                let st = self.build_status(&hash, &handle);
                return Ok(AddOutcome {
                    hash,
                    status: "added",
                    ready: st.ready,
                    peers: st.peers,
                    progress: st.progress,
                });
            }
        }

        Ok(AddOutcome {
            hash,
            status: "added",
            ready: false,
            peers: 0,
            progress: 0.0,
        })
    }

    fn spawn_background_add(
        &self,
        hash: &str,
        magnet: &str,
        mode: StartMode,
    ) -> tokio::sync::oneshot::Receiver<Result<(), BtError>> {
        // Spawn `session.add_torrent` on a detached task so cold DHT metadata resolution
        // (>15s) never blocks `/torrent/add` or gets aborted when an HTTP client disconnects.
        let (tx, rx) = tokio::sync::oneshot::channel::<Result<(), BtError>>();
        let session = Arc::clone(&self.session);
        let pending_adds = Arc::clone(&self.pending_adds);
        let prewarm_cursors = Arc::clone(&self.prewarm_cursors);
        let cache_dir = self.cache_dir.clone();
        let hash_bg = hash.to_string();
        let magnet_owned = magnet.to_string();

        let join = tokio::spawn(async move {
            let opts = AddTorrentOptions {
                paused: matches!(mode, StartMode::Paused),
                overwrite: true,
                only_files: Some(Vec::new()),
                ..AddTorrentOptions::default()
            };
            let add_res = session
                .add_torrent(AddTorrent::from_url(&magnet_owned), Some(opts))
                .await;

            let final_mode = pending_adds
                .write()
                .ok()
                .and_then(|mut map| map.remove(&hash_bg))
                .map_or(mode, |p| p.mode.0);

            match add_res {
                Ok(
                    AddTorrentResponse::Added(_, handle)
                    | AddTorrentResponse::AlreadyManaged(_, handle),
                ) => {
                    let empty = HashSet::new();
                    if !matches!(handle.only_files().as_deref(), Some([])) {
                        let _ = session.update_only_files(&handle, &empty).await;
                    }
                    match final_mode {
                        StartMode::Active => {
                            if matches!(handle.stats().state, TorrentStatsState::Paused) {
                                let _ = session.unpause(&handle).await;
                            }
                            let api = Api::new(Arc::clone(&session), None);
                            open_head_tail_prewarm_with(
                                &api,
                                &prewarm_cursors,
                                &cache_dir,
                                &hash_bg,
                                &handle,
                            )
                            .await;
                        }
                        StartMode::Paused => {
                            if !matches!(handle.stats().state, TorrentStatsState::Paused) {
                                let _ = session.pause(&handle).await;
                            }
                        }
                    }
                    let ready = pick_video_from_handle(&handle).is_some();
                    info!(
                        hash = %hash_bg,
                        ready,
                        "torrent added to librqbit (on-demand)"
                    );
                    let _ = tx.send(Ok(()));
                }
                Ok(AddTorrentResponse::ListOnly(_)) => {
                    let _ = tx.send(Err(BtError::Internal(
                        "unexpected list_only response from add_torrent".to_string(),
                    )));
                }
                Err(err) => {
                    warn!(hash = %hash_bg, error = %err, "background add_torrent failed");
                    let _ = tx.send(Err(BtError::Internal(format!("add_torrent failed: {err}"))));
                }
            }
        });

        if let Ok(mut pending) = self.pending_adds.write() {
            pending.insert(
                hash.to_string(),
                PendingAdd {
                    mode: PendingAddMode(mode),
                    abort: join.abort_handle(),
                },
            );
        }

        rx
    }

    /// Return detailed status for a managed torrent.
    ///
    /// # Errors
    /// Returns [`BtError::InvalidInput`] for a malformed hash or [`BtError::NotFound`]
    /// if the torrent is not managed.
    pub fn status(&self, raw_hash: &str) -> Result<TorrentStatusDto, BtError> {
        let hash = normalize_hash(raw_hash)
            .ok_or_else(|| BtError::InvalidInput("invalid info-hash".to_string()))?;
        let id = parse_torrent_id(&hash)?;
        if let Some(handle) = self.session.get(id) {
            return Ok(self.build_status(&hash, &handle));
        }
        if let Some(pending_mode) = self.pending_add_mode(&hash) {
            let state = match pending_mode {
                StartMode::Active => "downloading_metadata",
                StartMode::Paused => "paused",
            };
            return Ok(TorrentStatusDto {
                hash: hash.clone(),
                name: None,
                ready: false,
                cached: false,
                head_ready: false,
                peers: 0,
                progress: 0.0,
                download_rate: 0,
                upload_rate: 0,
                video_file: None,
                video_size: 0,
                local_size: 0,
                mime: "video/mp4",
                state,
                verified_pieces: 0,
                quality: "",
                piece_segments: Vec::new(),
                check_progress: 0.0,
                pinned: self.tracker.is_pinned(&hash),
            });
        }
        Err(BtError::NotFound(hash))
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
        let hash = normalize_hash(raw_hash)
            .ok_or_else(|| BtError::InvalidInput("invalid info-hash".to_string()))?;
        let id = parse_torrent_id(&hash)?;
        let Some(handle) = self.session.get(id) else {
            if let Ok(mut pending) = self.pending_adds.write() {
                if let Some(entry) = pending.get_mut(&hash) {
                    if matches!(mode, PauseMode::Force) || !self.tracker.is_pinned(&hash) {
                        entry.mode = PendingAddMode(StartMode::Paused);
                    }
                    if let Ok(mut fg) = self.last_foreground_at.write() {
                        fg.remove(&hash);
                    }
                    return Ok(());
                }
            }
            return Err(BtError::NotFound(hash));
        };
        {
            let mut cursors = self.seek_cursors.lock().await;
            cursors.remove(&hash);
        }
        {
            let mut prewarms = self.prewarm_cursors.lock().await;
            prewarms.remove(&hash);
        }
        if let Ok(mut offsets) = self.active_offsets.write() {
            offsets.remove(&hash);
        }
        if let Ok(mut fg) = self.last_foreground_at.write() {
            fg.remove(&hash);
        }
        if matches!(mode, PauseMode::Force) {
            let mut yielded = self.yielded_for_playback.lock().await;
            yielded.remove(&hash);
        }
        if matches!(mode, PauseMode::RespectPin)
            && self.tracker.is_pinned(&hash)
            && !self.is_torrent_prewarm_done(&hash, &handle)
        {
            debug!(hash = %hash, "keeping pinned (liked) torrent active until head+tail prewarm completes");
            self.ensure_head_prewarm(&hash, &handle).await;
            return Ok(());
        }
        if matches!(handle.stats().state, TorrentStatsState::Paused) {
            return Ok(());
        }
        self.session
            .pause(&handle)
            .await
            .map_err(|err| BtError::Internal(format!("pause failed: {err}")))
    }

    /// Resume (unpause) a managed torrent in strict on-demand mode and ensure head+tail prewarm.
    ///
    /// Idempotent: if the torrent is already live, avoids calling `librqbit::Session::unpause`
    /// (which returns an error on live torrents).
    ///
    /// # Errors
    /// Returns [`BtError::NotFound`] or [`BtError::Internal`].
    pub async fn resume(&self, raw_hash: &str) -> Result<(), BtError> {
        let hash = normalize_hash(raw_hash)
            .ok_or_else(|| BtError::InvalidInput("invalid info-hash".to_string()))?;
        let id = parse_torrent_id(&hash)?;
        let Some(handle) = self.session.get(id) else {
            if let Ok(mut pending) = self.pending_adds.write() {
                if let Some(entry) = pending.get_mut(&hash) {
                    entry.mode = PendingAddMode(StartMode::Active);
                    self.tracker.touch(&hash);
                    self.mark_foreground(&hash);
                    return Ok(());
                }
            }
            return Err(BtError::NotFound(hash));
        };
        self.tracker.touch(&hash);
        self.mark_foreground(&hash);
        self.enforce_on_demand_mode(&handle).await;
        if matches!(handle.stats().state, TorrentStatsState::Paused) {
            self.session
                .unpause(&handle)
                .await
                .map_err(|err| BtError::Internal(format!("unpause failed: {err}")))?;
        }
        if self.tracker.active_streams_for(&hash) == 0 {
            self.ensure_head_prewarm(&hash, &handle).await;
        }
        Ok(())
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
        self.mark_foreground(&hash);

        let Some(video) = pick_video_from_handle(&handle) else {
            return Ok(());
        };
        self.enforce_on_demand_mode(&handle).await;
        self.unpause_if_paused(&handle).await;

        let target_byte = byte_offset_for_time(time_sec, duration_sec, video.len);
        if let Ok(mut offsets) = self.active_offsets.write() {
            offsets.insert(hash.clone(), target_byte);
        }

        if is_video_finished(&handle, &handle.stats()) {
            return Ok(());
        }

        self.advance_play_cursor(&hash, &handle, video.id, target_byte)
            .await?;
        debug!(hash = %hash, target_byte, "seek prewarm cursor updated");
        Ok(())
    }

    /// Record the latest playback position for heatmap highlighting without opening a stream.
    pub fn note_playback_progress(&self, raw_hash: &str, time_sec: f64, duration_sec: f64) {
        let Ok((hash, handle)) = self.lookup_handle(raw_hash) else {
            return;
        };
        self.tracker.touch(&hash);
        self.mark_foreground(&hash);
        let Some(video) = pick_video_from_handle(&handle) else {
            return;
        };
        let offset = byte_offset_for_time(time_sec, duration_sec, video.len);
        if let Ok(mut offsets) = self.active_offsets.write() {
            offsets.insert(hash, offset);
        }
    }

    /// Record an active HTTP Range stream offset and keep a persistent playback `FileStream`
    /// cursor pinned at `offset_bytes` so `librqbit` keeps seeders connected and buffers
    /// strictly `[offset_bytes .. offset_bytes + 32 MiB]` between discrete browser Range bursts.
    pub async fn note_stream_offset(&self, raw_hash: &str, offset_bytes: u64) {
        let Ok((hash, handle)) = self.lookup_handle(raw_hash) else {
            return;
        };
        self.tracker.touch(&hash);
        self.mark_foreground(&hash);
        if let Ok(mut offsets) = self.active_offsets.write() {
            offsets.insert(hash.clone(), offset_bytes);
        }
        {
            let mut prewarms = self.prewarm_cursors.lock().await;
            prewarms.remove(&hash);
        }
        if is_video_finished(&handle, &handle.stats()) {
            let mut cursors = self.seek_cursors.lock().await;
            cursors.remove(&hash);
            return;
        }
        if let Some(video) = pick_video_from_handle(&handle) {
            let clamped = offset_bytes.min(video.len);
            let _ = self
                .advance_play_cursor(&hash, &handle, video.id, clamped)
                .await;
        }
    }

    /// Delete a torrent from the session, optionally removing downloaded files.
    ///
    /// # Errors
    /// Returns [`BtError::InvalidInput`] or [`BtError::Internal`].
    pub async fn remove(&self, raw_hash: &str, delete_files: DeleteFiles) -> Result<(), BtError> {
        let hash = normalize_hash(raw_hash)
            .ok_or_else(|| BtError::InvalidInput("invalid info-hash".to_string()))?;
        let id = parse_torrent_id(&hash)?;
        let aborted_pending = self
            .pending_adds
            .write()
            .ok()
            .and_then(|mut map| map.remove(&hash));
        if let Some(entry) = &aborted_pending {
            entry.abort.abort();
        }
        {
            let mut cursors = self.seek_cursors.lock().await;
            cursors.remove(&hash);
        }
        {
            let mut prewarms = self.prewarm_cursors.lock().await;
            prewarms.remove(&hash);
        }
        if let Ok(mut offsets) = self.active_offsets.write() {
            offsets.remove(&hash);
        }
        if let Ok(mut fg) = self.last_foreground_at.write() {
            fg.remove(&hash);
        }
        if self.session.get(id).is_none() && aborted_pending.is_some() {
            self.tracker.forget(&hash);
            return Ok(());
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
                let bytes = video_local_bytes(handle, &stats);
                self.tracker.snapshot_entry(&h, bytes)
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
        let has_foreground_playback = self.has_any_foreground_active();

        let mut live_bg: Vec<(String, u64, Arc<ManagedTorrent>)> =
            self.session.with_torrents(|iter| {
                iter.filter_map(|(_, handle)| {
                    let stats = handle.stats();
                    if is_video_finished(handle, &stats)
                        || !matches!(stats.state, TorrentStatsState::Live)
                    {
                        return None;
                    }
                    let h = handle.info_hash().as_string();
                    if self.is_foreground_active(&h) {
                        return None;
                    }
                    Some((h, video_local_bytes(handle, &stats), Arc::clone(handle)))
                })
                .collect()
            });

        if live_bg.is_empty() {
            return;
        }

        if over_watermark {
            let mut prewarms = self.prewarm_cursors.lock().await;
            for (h, _, handle) in &live_bg {
                prewarms.remove(h);
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
            let mut prewarms = self.prewarm_cursors.lock().await;
            let mut yielded = self.yielded_for_playback.lock().await;
            for (h, _, handle) in &live_bg {
                prewarms.remove(h);
                if self.session.pause(handle).await.is_ok() {
                    yielded.insert(h.clone());
                }
            }
            return;
        }

        if live_bg.len() > MAX_BACKGROUND_DOWNLOADS {
            // Keep the highest-progress torrents running so they complete fastest; pause the rest.
            live_bg.sort_by_key(|a| std::cmp::Reverse(a.1));
            let mut prewarms = self.prewarm_cursors.lock().await;
            let mut yielded = self.yielded_for_playback.lock().await;
            for (h, _, handle) in live_bg.iter().skip(MAX_BACKGROUND_DOWNLOADS) {
                prewarms.remove(h);
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
                if is_video_finished(handle, &stats)
                    || !matches!(stats.state, TorrentStatsState::Live)
                {
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
            {
                let mut prewarms = self.prewarm_cursors.lock().await;
                prewarms.remove(&h);
            }
            if self.session.pause(&handle).await.is_ok() {
                yielded.insert(h.clone());
                debug!(hash = %h, foreground = %foreground_hash, "yielded background download for playback");
            }
        }
    }

    /// Return `true` if a background torrent has already cached enough head+tail data
    /// (~32 MiB head + ~4 MiB tail) for instant playback without downloading the full file.
    fn is_torrent_prewarm_done(&self, hash: &str, handle: &ManagedTorrent) -> bool {
        let stats = handle.stats();
        if is_video_finished(handle, &stats) {
            return true;
        }
        let Some(video) = pick_video_from_handle(handle) else {
            return false;
        };
        let local_bytes = stats.file_progress.get(video.id).copied().unwrap_or(0);
        let bits = self.video_have_bits(hash, &video.piece_range);
        is_head_ready(&bits, video.len) && is_prewarm_satisfied(&bits, video.len, local_bytes)
    }

    fn video_have_bits(&self, hash: &str, piece_range: &Range<u32>) -> Vec<bool> {
        if piece_range.is_empty() {
            return Vec::new();
        }
        let Ok(id) = parse_torrent_id(hash) else {
            return Vec::new();
        };
        let Ok((bf, total_pieces)) = self.api.api_dump_haves(id) else {
            return Vec::new();
        };
        let start = usize::try_from(piece_range.start).unwrap_or(0);
        let end = usize::try_from(piece_range.end.min(total_pieces)).unwrap_or(start);
        let mut bits = Vec::with_capacity(end.saturating_sub(start));
        for idx in start..end {
            bits.push(bf.get(idx).as_deref().copied().unwrap_or(false));
        }
        bits
    }

    /// Ensure newly resolved `Live` torrents enter strict on-demand mode and open head+tail
    /// prewarm cursors even when metadata arrived after the initial `add_magnet`/`resume` call.
    pub async fn ensure_active_prewarms(&self) {
        let live: Vec<(String, Arc<ManagedTorrent>)> = self.session.with_torrents(|iter| {
            iter.filter_map(|(_, handle)| {
                let stats = handle.stats();
                if is_video_finished(handle, &stats)
                    || !matches!(stats.state, TorrentStatsState::Live)
                {
                    return None;
                }
                let h = handle.info_hash().as_string();
                if self.tracker.active_streams_for(&h) > 0 {
                    return None;
                }
                Some((h, Arc::clone(handle)))
            })
            .collect()
        });

        for (h, handle) in live {
            if pick_video_from_handle(&handle).is_none() {
                continue;
            }
            self.enforce_on_demand_mode(&handle).await;
            let has_seek_cursor = self.seek_cursors.lock().await.contains_key(&h);
            if !has_seek_cursor {
                self.ensure_head_prewarm(&h, &handle).await;
            }
        }
    }

    /// Periodic 5s maintenance: pause background prewarms that reached their head+tail budget,
    /// and resume yielded background downloads once foreground playback goes idle.
    pub async fn maintain_background_downloads(&self) {
        self.ensure_active_prewarms().await;

        let live_bg: Vec<(String, Arc<ManagedTorrent>)> = self.session.with_torrents(|iter| {
            iter.filter_map(|(_, handle)| {
                let stats = handle.stats();
                if is_video_finished(handle, &stats)
                    || !matches!(stats.state, TorrentStatsState::Live)
                {
                    return None;
                }
                let h = handle.info_hash().as_string();
                if self.tracker.active_streams_for(&h) > 0 {
                    return None;
                }
                Some((h, Arc::clone(handle)))
            })
            .collect()
        });

        for (h, handle) in live_bg {
            if self.is_foreground_active(&h) {
                continue;
            }
            if self.is_torrent_prewarm_done(&h, &handle) {
                {
                    let mut cursors = self.seek_cursors.lock().await;
                    cursors.remove(&h);
                }
                {
                    let mut prewarms = self.prewarm_cursors.lock().await;
                    prewarms.remove(&h);
                }
                if self.session.pause(&handle).await.is_ok() {
                    let mut yielded = self.yielded_for_playback.lock().await;
                    yielded.remove(&h);
                    info!(
                        hash = %h,
                        cap_mb = PREWARM_MAX_BYTES / (1024 * 1024),
                        "background head+tail prewarm satisfied; paused to save cache budget"
                    );
                }
            }
        }

        self.restore_yielded_if_idle().await;
    }

    /// Resume previously yielded background downloads once no playback stream is active
    /// and disk usage is below the 85% watermark.
    pub async fn restore_yielded_if_idle(&self) {
        if self.has_any_foreground_active() {
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
                !is_video_finished(h, &st) && matches!(st.state, TorrentStatsState::Live)
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
            if is_video_finished(&handle, &handle.stats())
                || self.is_torrent_prewarm_done(&h, &handle)
            {
                to_remove.push(h);
                continue;
            }
            self.enforce_on_demand_mode(&handle).await;
            if self.session.unpause(&handle).await.is_ok() {
                self.ensure_head_prewarm(&h, &handle).await;
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
    /// Automatically unpauses the torrent in strict on-demand mode (`only_files = empty`)
    /// so `librqbit` downloads strictly inside the active `FileStream`'s 32 MiB lookahead window.
    ///
    /// # Errors
    /// Returns [`BtError::NotFound`] if the torrent is unknown, [`BtError::NotReady`]
    /// if metadata has not yet been resolved, or [`BtError::Internal`] if stream
    /// creation fails.
    pub async fn open_stream(&self, raw_hash: &str) -> Result<OpenVideoStream, BtError> {
        let (hash, handle) = self.lookup_handle(raw_hash)?;

        let Some(video) = pick_video_from_handle(&handle) else {
            // Ensure torrent is active so metadata resolution progresses.
            self.unpause_if_paused(&handle).await;
            return Err(BtError::NotReady(format!(
                "metadata not yet resolved for {hash}"
            )));
        };

        self.enforce_on_demand_mode(&handle).await;
        self.unpause_if_paused(&handle).await;
        self.mark_foreground(&hash);

        // Single-cursor foreground focus: drop prewarm streams immediately so librqbit's
        // TorrentStreams::iter_next_pieces never splits/shuffles bandwidth away from playback.
        {
            let mut prewarms = self.prewarm_cursors.lock().await;
            prewarms.remove(&hash);
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

    fn mark_foreground(&self, hash: &str) {
        if let Ok(mut fg) = self.last_foreground_at.write() {
            fg.insert(hash.to_string(), Instant::now());
        }
    }

    fn is_foreground_active(&self, hash: &str) -> bool {
        if self.tracker.active_streams_for(hash) > 0 {
            return true;
        }
        self.last_foreground_at
            .read()
            .ok()
            .and_then(|fg| fg.get(hash).copied())
            .is_some_and(|ts| ts.elapsed() < FOREGROUND_GRACE)
    }

    fn has_any_foreground_active(&self) -> bool {
        if self.tracker.total_active_streams() > 0 {
            return true;
        }
        self.last_foreground_at
            .read()
            .is_ok_and(|fg| fg.values().any(|ts| ts.elapsed() < FOREGROUND_GRACE))
    }

    async fn advance_play_cursor(
        &self,
        hash: &str,
        handle: &Arc<ManagedTorrent>,
        file_id: usize,
        offset_bytes: u64,
    ) -> Result<(), BtError> {
        let mut cursors = self.seek_cursors.lock().await;
        if let Some(existing) = cursors.get_mut(hash) {
            if existing.seek(SeekFrom::Start(offset_bytes)).await.is_ok() {
                return Ok(());
            }
            cursors.remove(hash);
        }
        let mut stream = Arc::clone(handle)
            .stream(file_id)
            .await
            .map_err(|err| BtError::NotReady(format!("play cursor unavailable: {err}")))?;
        stream
            .seek(SeekFrom::Start(offset_bytes))
            .await
            .map_err(|err| BtError::Internal(format!("play cursor seek failed: {err}")))?;
        cursors.insert(hash.to_string(), Box::new(stream));
        Ok(())
    }

    fn pending_add_mode(&self, hash: &str) -> Option<StartMode> {
        self.pending_adds
            .read()
            .ok()
            .and_then(|map| map.get(hash).map(|p| p.mode.0))
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

    async fn unpause_if_paused(&self, handle: &Arc<ManagedTorrent>) {
        if matches!(handle.stats().state, TorrentStatsState::Paused) {
            if let Err(err) = self.session.unpause(handle).await {
                debug!(error = %err, "unpause_if_paused skipped");
            }
        }
    }

    /// Ensure `only_files` is empty so `librqbit` never queues bulk background pieces outside
    /// active `FileStream` lookahead windows.
    async fn enforce_on_demand_mode(&self, handle: &Arc<ManagedTorrent>) -> bool {
        if let Some(current) = handle.only_files() {
            if current.is_empty() {
                return true;
            }
        }
        let empty = HashSet::new();
        match self.session.update_only_files(handle, &empty).await {
            Ok(()) => true,
            Err(err) => {
                debug!(
                    error = %err,
                    "deferring on-demand only_files update (torrent still initializing)"
                );
                false
            }
        }
    }

    /// Open head (byte 0) + optional tail `FileStream` cursors using exact MP4 `moov` placement
    /// when known, focusing 100% of peer bandwidth on the minimum bytes needed for instant start.
    async fn ensure_head_prewarm(&self, hash: &str, handle: &Arc<ManagedTorrent>) {
        open_head_tail_prewarm_with(
            &self.api,
            &self.prewarm_cursors,
            &self.cache_dir,
            hash,
            handle,
        )
        .await;
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
        let video_finished = video_size > 0 && local_size >= video_size;
        let completion = if video_finished {
            VideoCompletion::Finished
        } else {
            VideoCompletion::InProgress
        };
        let state_label = map_state(&stats, completion);
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

        let (piece_segments, head_pieces_ok) = match piece_range {
            Some(range) if !range.is_empty() => {
                if video_finished {
                    let count = usize::try_from(range.end.saturating_sub(range.start)).unwrap_or(0);
                    let all_have = vec![true; count.clamp(1, PIECE_SEGMENT_BUCKETS)];
                    (
                        compute_piece_segments(&all_have, None, PIECE_SEGMENT_BUCKETS),
                        true,
                    )
                } else {
                    let bits = self.video_have_bits(hash, &range);
                    let moov = video_file.as_deref().map_or(MoovLocation::Unknown, |rel| {
                        inspect_disk_mp4_moov(&self.cache_dir, rel, video_size, &bits)
                    });
                    let head_ok = is_head_ready_for_moov(&bits, video_size, moov);
                    let segs = compute_piece_segments(&bits, active_ratio, PIECE_SEGMENT_BUCKETS);
                    (segs, head_ok)
                }
            }
            _ => (Vec::new(), false),
        };

        let head_ready = ready && (video_finished || head_pieces_ok);

        TorrentStatusDto {
            hash: hash.to_string(),
            name,
            ready,
            cached: local_size > CACHED_MIN_BYTES,
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

fn video_have_bits_with_api(api: &Api, hash: &str, piece_range: &Range<u32>) -> Vec<bool> {
    if piece_range.is_empty() {
        return Vec::new();
    }
    let Ok(id) = parse_torrent_id(hash) else {
        return Vec::new();
    };
    let Ok((bf, total_pieces)) = api.api_dump_haves(id) else {
        return Vec::new();
    };
    let start = usize::try_from(piece_range.start).unwrap_or(0);
    let end = usize::try_from(piece_range.end.min(total_pieces)).unwrap_or(start);
    let mut bits = Vec::with_capacity(end.saturating_sub(start));
    for idx in start..end {
        bits.push(bf.get(idx).as_deref().copied().unwrap_or(false));
    }
    bits
}

async fn open_head_tail_prewarm_with(
    api: &Api,
    prewarm_cursors: &Mutex<PrewarmCursorMap>,
    cache_dir: &Path,
    hash: &str,
    handle: &Arc<ManagedTorrent>,
) {
    if is_video_finished(handle, &handle.stats()) {
        return;
    }
    let Some(video) = pick_video_from_handle(handle) else {
        return;
    };
    let bits = video_have_bits_with_api(api, hash, &video.piece_range);
    let moov = inspect_disk_mp4_moov(cache_dir, &video.rel_path, video.len, &bits);
    if is_head_ready_for_moov(&bits, video.len, moov) {
        return;
    }
    {
        let prewarms = prewarm_cursors.lock().await;
        if prewarms.contains_key(hash) {
            return;
        }
    }

    let mut streams: Vec<Box<dyn AsyncVideoStream>> = Vec::with_capacity(2);
    if let Ok(head_stream) = Arc::clone(handle).stream(video.id).await {
        streams.push(Box::new(head_stream));
    }
    // Fast-start MP4 (`MoovLocation::Head`) needs zero tail bytes; keep a single head stream
    // so librqbit never splits peer bandwidth with a tail cursor.
    let tail_offset = match moov {
        MoovLocation::Tail { start_offset } => Some(start_offset),
        MoovLocation::Unknown if video.len > HEAD_READY_CONTIGUOUS_BYTES => {
            Some(video.len.saturating_sub(TAIL_PREWARM_BYTES))
        }
        MoovLocation::Head { .. } | MoovLocation::Unknown => None,
    };
    if let Some(offset) = tail_offset {
        if let Ok(mut tail_stream) = Arc::clone(handle).stream(video.id).await {
            if tail_stream.seek(SeekFrom::Start(offset)).await.is_ok() {
                streams.push(Box::new(tail_stream));
            }
        }
    }

    if !streams.is_empty() {
        let mut prewarms = prewarm_cursors.lock().await;
        prewarms.insert(hash.to_string(), streams);
        debug!(hash = %hash, moov = ?moov, "opened on-demand prewarm cursors");
    }
}

fn video_local_bytes(handle: &ManagedTorrent, stats: &librqbit::TorrentStats) -> u64 {
    pick_video_from_handle(handle).map_or(stats.progress_bytes, |v| {
        stats.file_progress.get(v.id).copied().unwrap_or(0)
    })
}

fn is_video_finished(handle: &ManagedTorrent, stats: &librqbit::TorrentStats) -> bool {
    pick_video_from_handle(handle)
        .is_some_and(|v| v.len > 0 && stats.file_progress.get(v.id).copied().unwrap_or(0) >= v.len)
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

/// Inspect the on-disk MP4 top-level boxes once piece 0 is verified on disk.
fn inspect_disk_mp4_moov(
    cache_dir: &Path,
    rel_path: &str,
    file_len: u64,
    have_bits: &[bool],
) -> MoovLocation {
    if !have_bits.first().copied().unwrap_or(false) {
        return MoovLocation::Unknown;
    }
    let full_path = cache_dir.join(rel_path);
    let Ok(mut file) = std::fs::File::open(full_path) else {
        return MoovLocation::Unknown;
    };
    let mut buf = vec![0_u8; MP4_HEAD_INSPECT_BYTES];
    let Ok(n) = file.read(&mut buf) else {
        return MoovLocation::Unknown;
    };
    inspect_mp4_head(&buf[..n], file_len)
}

/// Check `head_ready` using exact MP4 `moov` box boundaries when known, falling back to
/// [`is_head_ready`] (10 MiB contiguous head + tail piece) for unknown containers.
#[must_use]
pub fn is_head_ready_for_moov(have_bits: &[bool], file_len: u64, moov: MoovLocation) -> bool {
    let total_pieces = have_bits.len();
    if file_len == 0 || total_pieces == 0 {
        return false;
    }
    match moov {
        MoovLocation::Head { end_offset } => {
            // Fast-start MP4: only need contiguous head covering `moov` + 2 MiB keyframes;
            // no tail piece required!
            let target_bytes = end_offset
                .saturating_add(FAST_START_KEYFRAME_BUFFER_BYTES)
                .min(HEAD_READY_CONTIGUOUS_BYTES)
                .min(file_len);
            let head_count = pieces_for_bytes(total_pieces, file_len, target_bytes);
            have_bits.iter().take(head_count).all(|&b| b)
        }
        MoovLocation::Tail { start_offset } => {
            // Tail-moov MP4: need initial keyframes (2 MiB) + exact tail `[start_offset..EOF]`.
            let head_bytes = FAST_START_KEYFRAME_BUFFER_BYTES.min(file_len);
            let head_count = pieces_for_bytes(total_pieces, file_len, head_bytes);
            let tail_bytes = file_len.saturating_sub(start_offset).max(1);
            let tail_count = pieces_for_bytes(total_pieces, file_len, tail_bytes);
            let head_ok = have_bits.iter().take(head_count).all(|&b| b);
            let tail_ok = have_bits.iter().rev().take(tail_count).all(|&b| b);
            head_ok && tail_ok
        }
        MoovLocation::Unknown => is_head_ready(have_bits, file_len),
    }
}

fn pieces_for_bytes(total_pieces: usize, file_len: u64, bytes: u64) -> usize {
    let total_pieces_u128 = u128::try_from(total_pieces).unwrap_or(1);
    let file_len_u128 = u128::from(file_len.max(1));
    usize::try_from(
        total_pieces_u128
            .saturating_mul(u128::from(bytes))
            .div_ceil(file_len_u128),
    )
    .unwrap_or(1)
    .clamp(1, total_pieces)
}

/// Check whether contiguous head pieces covering [`HEAD_READY_CONTIGUOUS_BYTES`] (10 MiB,
/// enough for `ftyp` + large FHD/4K MP4 `moov` atoms + initial keyframes) AND the final piece
/// (for tail-`moov` MP4s) are present on disk without holes.
#[must_use]
pub fn is_head_ready(have_bits: &[bool], file_len: u64) -> bool {
    let total_pieces = have_bits.len();
    if file_len == 0 || total_pieces == 0 {
        return false;
    }
    if file_len <= HEAD_READY_CONTIGUOUS_BYTES {
        return have_bits.iter().all(|&b| b);
    }
    let total_pieces_u128 = u128::try_from(total_pieces).unwrap_or(1);
    let file_len_u128 = u128::from(file_len);
    let head_count = usize::try_from(
        total_pieces_u128
            .saturating_mul(u128::from(HEAD_READY_CONTIGUOUS_BYTES))
            .div_ceil(file_len_u128),
    )
    .unwrap_or(1)
    .clamp(1, total_pieces);

    let head_ok = have_bits.iter().take(head_count).all(|&b| b);
    let tail_ok = have_bits.last().copied().unwrap_or(false);
    head_ok && tail_ok
}

/// Check whether a background prewarm has cached enough head (~32 MiB) + tail (~4 MiB)
/// data to guarantee instant playback without downloading the full video file.
#[must_use]
pub fn is_prewarm_satisfied(have_bits: &[bool], file_len: u64, local_bytes: u64) -> bool {
    if file_len == 0 {
        return false;
    }
    if file_len <= PREWARM_MAX_BYTES {
        return local_bytes >= file_len || (!have_bits.is_empty() && have_bits.iter().all(|&b| b));
    }
    if local_bytes >= PREWARM_MAX_BYTES {
        return true;
    }
    let total_pieces = have_bits.len();
    if total_pieces == 0 {
        return false;
    }
    let total_pieces_u128 = u128::try_from(total_pieces).unwrap_or(1);
    let file_len_u128 = u128::from(file_len);
    let head_count = usize::try_from(
        total_pieces_u128
            .saturating_mul(u128::from(PREWARM_HEAD_BYTES))
            .div_ceil(file_len_u128),
    )
    .unwrap_or(1)
    .clamp(1, total_pieces);
    let tail_count = usize::try_from(
        total_pieces_u128
            .saturating_mul(u128::from(PREWARM_TAIL_BYTES))
            .div_ceil(file_len_u128),
    )
    .unwrap_or(1)
    .clamp(1, total_pieces);

    let head_ok = have_bits.iter().take(head_count).all(|&b| b);
    let tail_ok = have_bits.iter().rev().take(tail_count).all(|&b| b);
    head_ok && tail_ok
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

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
enum VideoCompletion {
    InProgress,
    Finished,
}

fn map_state(stats: &librqbit::TorrentStats, completion: VideoCompletion) -> &'static str {
    if matches!(completion, VideoCompletion::Finished) {
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

    #[test]
    fn head_ready_requires_contiguous_moov_window_and_tail_piece() {
        // 6 GiB video with 3000 pieces (2 MiB/piece): 10 MiB contiguous head = 5 pieces + last piece.
        let file_len = 6 * 1024 * 1024 * 1024_u64;
        let mut bits = vec![false; 3000];
        assert!(!is_head_ready(&bits, file_len));

        // Scattered pieces (simulating 1% / 50 MiB downloaded with a hole at piece 2 inside moov)
        bits[0] = true;
        bits[1] = true;
        bits[3] = true;
        bits[4] = true;
        bits[100] = true;
        bits[2999] = true;
        assert!(
            !is_head_ready(&bits, file_len),
            "hole inside 10 MiB moov window must not report head_ready"
        );

        // Fill the hole at piece 2 -> contiguous pieces 0..5 + tail piece 2999 -> ready!
        bits[2] = true;
        assert!(is_head_ready(&bits, file_len));

        // Missing tail piece -> not yet ready for tail-moov MP4s
        bits[2999] = false;
        assert!(!is_head_ready(&bits, file_len));
    }

    #[test]
    fn prewarm_requires_head_and_tail_or_budget_cap() {
        // 6 GiB video with 1000 pieces (~6 MiB/piece):
        // head ~32 MiB -> ~6 pieces, tail ~4 MiB -> 1 piece.
        let file_len = 6 * 1024 * 1024 * 1024_u64;
        let mut bits = vec![false; 1000];
        assert!(!is_prewarm_satisfied(&bits, file_len, 0));

        // Head only -> not yet satisfied (tail moov missing)
        for b in bits.iter_mut().take(8) {
            *b = true;
        }
        assert!(!is_prewarm_satisfied(&bits, file_len, 24 * 1024 * 1024));

        // Head + tail -> satisfied!
        for b in bits.iter_mut().rev().take(2) {
            *b = true;
        }
        assert!(is_prewarm_satisfied(&bits, file_len, 28 * 1024 * 1024));

        // Hard 36 MiB cap -> satisfied even if pieces are scattered
        let empty_bits = vec![false; 1000];
        assert!(is_prewarm_satisfied(
            &empty_bits,
            file_len,
            PREWARM_MAX_BYTES
        ));
    }
}
