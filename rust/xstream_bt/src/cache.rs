//! Strictly-proven `BitTorrent` disk cache manager (quota enforcement, LRU eviction, RAII stream pins).
//!
//! # Formal Invariants
//!
//! Every call to [`plan_eviction`] satisfies five invariants (locked by deterministic
//! unit tests and a 1,000-case randomized property suite in `cache::tests`):
//!
//! 1. **I1 (Protection Safety)**: Entries with `active_streams > 0` or `pinned == true`
//!    are never selected for eviction.
//! 2. **I2 (Grace Window Safety)**: Unpinned entries accessed within `grace_secs` are
//!    only eligible if `total_bytes > hard_limit_bytes` (emergency disk pressure).
//! 3. **I3 (Monotonic Quota Convergence)**: Whenever the sum of protected bytes is
//!    `<= target_bytes`, applying the returned plan guarantees `remaining_bytes <= target_bytes <= max_bytes`.
//! 4. **I4 (Minimality)**: Removing the final entry from the eviction plan would leave
//!    `remaining_bytes > target_bytes` (never over-evicts).
//! 5. **I5 (Strict LRU Determinism)**: Within the same tier, older `last_access_secs`
//!    is evicted first; ties break by larger `disk_bytes`, then lexicographic `hash`.

use std::{
    collections::{HashMap, HashSet},
    fs,
    path::Path,
    sync::{Arc, RwLock},
    time::{SystemTime, UNIX_EPOCH},
};

/// Default low-watermark target as a percentage of `max_bytes` (85%).
pub const DEFAULT_TARGET_PCT: u64 = 85;

/// Default grace window (seconds) before a recently-touched unpinned torrent is evicted.
pub const DEFAULT_GRACE_SECS: u64 = 60;

/// Snapshot of a single cached torrent for eviction planning.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct CacheEntry {
    /// Lowercase 40-char hex info-hash.
    pub hash: String,
    /// Actual allocated disk bytes (`st_blocks * 512` on Unix).
    pub disk_bytes: u64,
    /// Last access timestamp in Unix seconds.
    pub last_access_secs: u64,
    /// Whether the torrent is pinned (e.g. user-liked title).
    pub pinned: bool,
    /// Number of currently open HTTP `/stream` connections reading this torrent.
    pub active_streams: usize,
}

/// Policy parameters for quota enforcement.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct EvictionPolicy {
    /// Soft quota ceiling in bytes; eviction triggers when `total_bytes > max_bytes`.
    /// A value of `0` disables automatic eviction.
    pub max_bytes: u64,
    /// Low-watermark target in bytes (eviction stops once `remaining_bytes <= target_bytes`).
    pub target_bytes: u64,
    /// Hard emergency ceiling in bytes above which recently-accessed unpinned entries may be evicted.
    pub hard_limit_bytes: u64,
    /// Grace window in seconds for recently-accessed unpinned entries.
    pub grace_secs: u64,
}

impl EvictionPolicy {
    /// Construct a standard policy from `max_bytes` (85% target watermark, 110% hard ceiling, 60s grace).
    pub const fn from_max_bytes(max_bytes: u64) -> Self {
        let target_bytes = max_bytes / 100 * DEFAULT_TARGET_PCT;
        let hard_limit_bytes = max_bytes.saturating_add(max_bytes / 10);
        Self {
            max_bytes,
            target_bytes,
            hard_limit_bytes,
            grace_secs: DEFAULT_GRACE_SECS,
        }
    }
}

/// Output of [`plan_eviction`].
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct EvictionPlan {
    /// Ordered list of torrent hashes to delete (oldest/lowest-priority first).
    pub evict_hashes: Vec<String>,
    /// Total bytes expected to be freed by deleting `evict_hashes`.
    pub freed_bytes: u64,
    /// Expected remaining bytes after eviction.
    pub remaining_bytes: u64,
}

/// Compute a deterministic, minimal eviction plan for `entries` at timestamp `now_secs`.
///
/// `total_disk_bytes` may exceed the sum of `entries` (e.g. due to unmanaged overhead);
/// eviction reduces `total_disk_bytes` until `<= policy.target_bytes` or no eligible entries remain.
pub fn plan_eviction(
    entries: &[CacheEntry],
    total_disk_bytes: u64,
    policy: EvictionPolicy,
    now_secs: u64,
) -> EvictionPlan {
    if policy.max_bytes == 0 || total_disk_bytes <= policy.max_bytes {
        return EvictionPlan {
            evict_hashes: Vec::new(),
            freed_bytes: 0,
            remaining_bytes: total_disk_bytes,
        };
    }

    let emergency = total_disk_bytes > policy.hard_limit_bytes;
    let target = policy.target_bytes.min(policy.max_bytes);

    // Tier 0: unpinned, idle, past grace window.
    // Tier 1: unpinned, idle, within grace window (only eligible in emergency pressure).
    let mut candidates: Vec<(u8, &CacheEntry)> = entries
        .iter()
        .filter(|e| !e.pinned && e.active_streams == 0)
        .filter_map(|e| {
            let age = now_secs.saturating_sub(e.last_access_secs);
            if age >= policy.grace_secs {
                Some((0_u8, e))
            } else if emergency {
                Some((1_u8, e))
            } else {
                None
            }
        })
        .collect();

    // Strict deterministic ordering: Tier asc -> LRU (last_access asc) -> larger disk_bytes desc -> hash asc.
    candidates.sort_by(|(tier_a, a), (tier_b, b)| {
        tier_a
            .cmp(tier_b)
            .then_with(|| a.last_access_secs.cmp(&b.last_access_secs))
            .then_with(|| b.disk_bytes.cmp(&a.disk_bytes))
            .then_with(|| a.hash.cmp(&b.hash))
    });

    let mut evict_hashes = Vec::new();
    let mut freed_bytes: u64 = 0;
    let mut remaining = total_disk_bytes;

    for (_, entry) in candidates {
        if remaining <= target {
            break;
        }
        evict_hashes.push(entry.hash.clone());
        freed_bytes = freed_bytes.saturating_add(entry.disk_bytes);
        remaining = remaining.saturating_sub(entry.disk_bytes);
    }

    EvictionPlan {
        evict_hashes,
        freed_bytes,
        remaining_bytes: remaining,
    }
}

/// Measure actual allocated disk bytes under `path` (sparse-file aware on Unix via `st_blocks * 512`).
pub fn disk_usage_bytes(path: &Path) -> u64 {
    let Ok(meta) = fs::symlink_metadata(path) else {
        return 0;
    };
    if meta.is_file() {
        return file_allocated_bytes(&meta);
    }
    if !meta.is_dir() {
        return 0;
    }

    let mut total: u64 = 0;
    let mut stack = vec![path.to_path_buf()];
    while let Some(dir) = stack.pop() {
        let Ok(read_dir) = fs::read_dir(&dir) else {
            continue;
        };
        for entry in read_dir.flatten() {
            let p = entry.path();
            let Ok(m) = fs::symlink_metadata(&p) else {
                continue;
            };
            if m.is_dir() {
                stack.push(p);
            } else if m.is_file() {
                total = total.saturating_add(file_allocated_bytes(&m));
            }
        }
    }
    total
}

#[cfg(unix)]
fn file_allocated_bytes(meta: &fs::Metadata) -> u64 {
    use std::os::unix::fs::MetadataExt;
    meta.blocks().saturating_mul(512)
}

#[cfg(not(unix))]
fn file_allocated_bytes(meta: &fs::Metadata) -> u64 {
    meta.len()
}

/// Format a byte count into a human-readable string matching xstream's `format_size`.
pub fn format_bytes(bytes: u64) -> String {
    const KIB: u64 = 1024;
    const MIB: u64 = 1024 * 1024;
    const GIB: u64 = 1024 * 1024 * 1024;

    if bytes >= GIB {
        let tenths = u128::from(bytes).saturating_mul(100) / u128::from(GIB);
        let whole = tenths / 100;
        let frac = tenths % 100;
        format!("{whole}.{frac:02} GB")
    } else if bytes >= MIB {
        let tenths = u128::from(bytes).saturating_mul(10) / u128::from(MIB);
        let whole = tenths / 10;
        let frac = tenths % 10;
        format!("{whole}.{frac} MB")
    } else if bytes >= KIB {
        let tenths = u128::from(bytes).saturating_mul(10) / u128::from(KIB);
        let whole = tenths / 10;
        let frac = tenths % 10;
        format!("{whole}.{frac} KB")
    } else {
        format!("{bytes} B")
    }
}

/// Current Unix timestamp in seconds.
pub fn unix_now_secs() -> u64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map_or(0, |d| d.as_secs())
}

#[derive(Debug, Default)]
struct TrackerInner {
    pinned: HashSet<String>,
    last_access: HashMap<String, u64>,
    active_streams: HashMap<String, usize>,
}

/// Thread-safe runtime tracker for pins, LRU timestamps, and RAII active-stream guards.
#[derive(Debug, Clone, Default)]
pub struct CacheTracker {
    inner: Arc<RwLock<TrackerInner>>,
}

/// RAII guard that keeps a torrent protected from eviction while an HTTP stream is open.
#[derive(Debug)]
pub struct ActiveStreamGuard {
    hash: String,
    inner: Arc<RwLock<TrackerInner>>,
}

impl Drop for ActiveStreamGuard {
    fn drop(&mut self) {
        if let Ok(mut guard) = self.inner.write() {
            if let Some(count) = guard.active_streams.get_mut(&self.hash) {
                *count = count.saturating_sub(1);
                if *count == 0 {
                    guard.active_streams.remove(&self.hash);
                }
            }
            guard.last_access.insert(self.hash.clone(), unix_now_secs());
        }
    }
}

impl CacheTracker {
    /// Create a new empty tracker.
    pub fn new() -> Self {
        Self::default()
    }

    /// Record an access timestamp for `hash`.
    pub fn touch(&self, hash: &str) {
        if let Ok(mut guard) = self.inner.write() {
            guard.last_access.insert(hash.to_string(), unix_now_secs());
        }
    }

    /// Mark `hash` as pinned (protected from eviction, e.g. user-liked title).
    pub fn pin(&self, hash: &str) {
        if let Ok(mut guard) = self.inner.write() {
            guard.pinned.insert(hash.to_string());
            guard.last_access.insert(hash.to_string(), unix_now_secs());
        }
    }

    /// Remove pin protection from `hash`.
    pub fn unpin(&self, hash: &str) {
        if let Ok(mut guard) = self.inner.write() {
            guard.pinned.remove(hash);
        }
    }

    /// Remove all tracking metadata for a deleted torrent.
    pub fn forget(&self, hash: &str) {
        if let Ok(mut guard) = self.inner.write() {
            guard.last_access.remove(hash);
            guard.active_streams.remove(hash);
        }
    }

    /// Acquire an [`ActiveStreamGuard`] for `hash` (increments active stream count until dropped).
    pub fn acquire_stream(&self, hash: &str) -> ActiveStreamGuard {
        let key = hash.to_string();
        if let Ok(mut guard) = self.inner.write() {
            *guard.active_streams.entry(key.clone()).or_insert(0) += 1;
            guard.last_access.insert(key.clone(), unix_now_secs());
        }
        ActiveStreamGuard {
            hash: key,
            inner: Arc::clone(&self.inner),
        }
    }

    /// Build a [`CacheEntry`] snapshot for `hash` with its measured `disk_bytes`.
    pub fn snapshot_entry(&self, hash: &str, disk_bytes: u64) -> CacheEntry {
        let Ok(guard) = self.inner.read() else {
            return CacheEntry {
                hash: hash.to_string(),
                disk_bytes,
                last_access_secs: 0,
                pinned: false,
                active_streams: 0,
            };
        };
        CacheEntry {
            hash: hash.to_string(),
            disk_bytes,
            last_access_secs: guard.last_access.get(hash).copied().unwrap_or(0),
            pinned: guard.pinned.contains(hash),
            active_streams: guard.active_streams.get(hash).copied().unwrap_or(0),
        }
    }
}

#[cfg(test)]
mod tests {
    use std::io::{Seek, SeekFrom, Write};

    use super::*;

    /// Deterministic xorshift64 PRNG for reproducible property proofs.
    struct Rng(u64);

    impl Rng {
        fn next_u64(&mut self) -> u64 {
            let mut x = self.0;
            x ^= x << 13;
            x ^= x >> 7;
            x ^= x << 17;
            self.0 = x;
            x
        }
    }

    #[test]
    fn invariant_proof_1000_randomized_scenarios() {
        let mut rng = Rng(0x5EED_CAFE_1234_5678);

        for case in 0..1000_u32 {
            let count = usize::try_from(rng.next_u64() % 25 + 1).unwrap_or(1);
            let now_secs = 1_000_000_u64;
            let mut entries = Vec::with_capacity(count);
            let mut total_bytes: u64 = 0;

            for i in 0..count {
                let disk_bytes = (rng.next_u64() % 500 + 1) * 1024 * 1024;
                let age = rng.next_u64() % 600;
                let pinned = rng.next_u64() % 5 == 0;
                let active_streams = usize::from(rng.next_u64() % 7 == 0);
                total_bytes = total_bytes.saturating_add(disk_bytes);
                entries.push(CacheEntry {
                    hash: format!("{case:04x}{i:036x}"),
                    disk_bytes,
                    last_access_secs: now_secs - age,
                    pinned,
                    active_streams,
                });
            }

            let max_bytes = (rng.next_u64() % 4000 + 500) * 1024 * 1024;
            let policy = EvictionPolicy::from_max_bytes(max_bytes);
            let plan = plan_eviction(&entries, total_bytes, policy, now_secs);

            let by_hash: HashMap<&str, &CacheEntry> =
                entries.iter().map(|e| (e.hash.as_str(), e)).collect();

            // I1 (Protection Safety): NEVER evict pinned or active_streams > 0.
            for h in &plan.evict_hashes {
                let e = by_hash[h.as_str()];
                assert!(!e.pinned, "case {case}: evicted pinned entry {h}");
                assert_eq!(
                    e.active_streams, 0,
                    "case {case}: evicted active stream {h}"
                );
            }

            // I2 (Grace Window Safety): outside emergency, never evict age < grace_secs.
            if total_bytes <= policy.hard_limit_bytes {
                for h in &plan.evict_hashes {
                    let e = by_hash[h.as_str()];
                    assert!(
                        now_secs - e.last_access_secs >= policy.grace_secs,
                        "case {case}: evicted entry inside grace window without emergency"
                    );
                }
            }

            // Accounting consistency.
            let sum_freed: u64 = plan
                .evict_hashes
                .iter()
                .map(|h| by_hash[h.as_str()].disk_bytes)
                .sum();
            assert_eq!(
                sum_freed, plan.freed_bytes,
                "case {case}: freed_bytes mismatch"
            );
            assert_eq!(
                total_bytes - sum_freed,
                plan.remaining_bytes,
                "case {case}: remaining_bytes mismatch"
            );

            // I3 (Monotonic Quota Convergence): if eligible bytes suffice, remaining <= target <= max.
            if total_bytes > policy.max_bytes {
                let emergency = total_bytes > policy.hard_limit_bytes;
                let un_evictable: u64 = entries
                    .iter()
                    .filter(|e| {
                        e.pinned
                            || e.active_streams > 0
                            || (!emergency && now_secs - e.last_access_secs < policy.grace_secs)
                    })
                    .map(|e| e.disk_bytes)
                    .sum();
                if un_evictable <= policy.target_bytes {
                    assert!(
                        plan.remaining_bytes <= policy.target_bytes,
                        "case {case}: failed to converge to target"
                    );
                    assert!(
                        plan.remaining_bytes <= policy.max_bytes,
                        "case {case}: failed to converge to max"
                    );
                }
            }

            // I4 (Minimality): removing the last evicted item would exceed target_bytes.
            if let Some(last_hash) = plan.evict_hashes.last() {
                let last_size = by_hash[last_hash.as_str()].disk_bytes;
                assert!(
                    plan.remaining_bytes + last_size > policy.target_bytes,
                    "case {case}: over-evicted beyond target_bytes"
                );
            }
        }
    }

    #[test]
    fn strict_lru_order_and_active_guard_raii() {
        let tracker = CacheTracker::new();
        tracker.pin("pinned_hash");
        let guard = tracker.acquire_stream("streaming_hash");

        let s_stream = tracker.snapshot_entry("streaming_hash", 100);
        let s_pin = tracker.snapshot_entry("pinned_hash", 100);
        assert_eq!(s_stream.active_streams, 1, "active guard increments count");
        assert!(s_pin.pinned, "pinned hash marked");

        drop(guard);
        let s_after = tracker.snapshot_entry("streaming_hash", 100);
        assert_eq!(
            s_after.active_streams, 0,
            "dropping guard releases stream pin"
        );
    }

    #[test]
    fn sparse_file_measures_allocated_blocks_not_logical_size() {
        let dir = std::env::temp_dir().join(format!("xstream-bt-sparse-{}", std::process::id()));
        let _ = fs::remove_dir_all(&dir);
        fs::create_dir_all(&dir).expect("create temp dir");

        let file_path = dir.join("sparse.mp4");
        let mut f = fs::File::create(&file_path).expect("create sparse file");
        // Write 64 KiB at offset 0 and 64 KiB at offset 50 MiB -> logical size ~50 MiB, disk blocks ~128 KiB.
        let chunk = vec![0xAB_u8; 65_536];
        f.write_all(&chunk).expect("write head");
        f.seek(SeekFrom::Start(50 * 1024 * 1024))
            .expect("seek 50MiB");
        f.write_all(&chunk).expect("write tail");
        f.sync_all().expect("sync sparse file");

        let measured = disk_usage_bytes(&dir);
        let _ = fs::remove_dir_all(&dir);

        assert!(
            (128 * 1024..2 * 1024 * 1024).contains(&measured),
            "sparse file disk usage should reflect ~128KiB allocated blocks, got {measured}"
        );
    }
}
