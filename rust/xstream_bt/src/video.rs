//! Pure helpers for video file selection, MIME detection, and magnet hash parsing.

use std::path::Path;

/// Supported video file extensions (lowercase, without leading dot).
const VIDEO_EXTENSIONS: &[&str] = &["mp4", "mkv", "webm", "m4v", "avi", "mov", "ts"];

/// Minimum file size (10 MiB) to treat a video file as a real feature rather than an ad clip.
const MIN_MAIN_VIDEO_BYTES: u64 = 10 * 1024 * 1024;

/// A candidate file inside a torrent.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct FileCandidate<'a> {
    /// Zero-based file index inside the torrent metadata.
    pub id: usize,
    /// Relative path of the file inside the torrent.
    pub path: &'a Path,
    /// Uncompressed file length in bytes.
    pub len: u64,
}

/// Select the primary playable video file from a torrent's file list.
///
/// Strategy:
/// 1. Filter to known video extensions.
/// 2. Prefer files `>= 10 MiB` (filters out tiny tracker ad clips like `javcall.com.mp4`).
/// 3. Pick the largest file by byte length.
pub fn select_video_file<'a>(files: &[FileCandidate<'a>]) -> Option<FileCandidate<'a>> {
    let videos: Vec<&FileCandidate<'a>> = files.iter().filter(|f| is_video_path(f.path)).collect();

    if videos.is_empty() {
        return None;
    }

    let main_videos: Vec<&FileCandidate<'a>> = videos
        .iter()
        .copied()
        .filter(|f| f.len >= MIN_MAIN_VIDEO_BYTES)
        .collect();

    let pool = if main_videos.is_empty() {
        &videos
    } else {
        &main_videos
    };

    pool.iter().copied().max_by_key(|f| f.len).cloned()
}

/// Check whether a path has a supported video extension.
pub fn is_video_path(path: &Path) -> bool {
    path.extension()
        .and_then(|ext| ext.to_str())
        .is_some_and(|ext| {
            VIDEO_EXTENSIONS
                .iter()
                .any(|known| ext.eq_ignore_ascii_case(known))
        })
}

/// Return the HTTP `Content-Type` MIME string for a video path.
pub fn mime_for_path(path: &Path) -> &'static str {
    let ext = path
        .extension()
        .and_then(|e| e.to_str())
        .map(str::to_ascii_lowercase);

    match ext.as_deref() {
        Some("mkv") => "video/x-matroska",
        Some("webm") => "video/webm",
        Some("avi") => "video/x-msvideo",
        Some("mov") => "video/quicktime",
        Some("ts") => "video/mp2t",
        _ => "video/mp4",
    }
}

/// Validate and normalize a 40-character hexadecimal SHA-1 info-hash to lowercase.
pub fn normalize_hash(raw: &str) -> Option<String> {
    let trimmed = raw.trim();
    if trimmed.len() == 40 && trimmed.bytes().all(|b| b.is_ascii_hexdigit()) {
        Some(trimmed.to_ascii_lowercase())
    } else {
        None
    }
}

/// Extract a lowercase 40-character hex info-hash from either a magnet URI or bare hash.
pub fn extract_info_hash(magnet_or_hash: &str) -> Option<String> {
    let trimmed = magnet_or_hash.trim();
    if let Some(h) = normalize_hash(trimmed) {
        return Some(h);
    }

    let lower = trimmed.to_ascii_lowercase();
    let marker = "xt=urn:btih:";
    let idx = lower.find(marker)?;
    let rest = &lower[idx + marker.len()..];
    let hash_part = rest.split('&').next().unwrap_or(rest);
    normalize_hash(hash_part)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn picks_largest_main_video_skipping_ads() {
        let files = [
            FileCandidate {
                id: 0,
                path: Path::new("readme.txt"),
                len: 1024,
            },
            FileCandidate {
                id: 1,
                path: Path::new("javcall.com.mp4"),
                len: 2 * 1024 * 1024,
            },
            FileCandidate {
                id: 2,
                path: Path::new("SNOS-524-FHD.mp4"),
                len: 4_500_000_000,
            },
            FileCandidate {
                id: 3,
                path: Path::new("cover.jpg"),
                len: 500_000,
            },
        ];
        let picked = select_video_file(&files);
        assert_eq!(picked.map(|f| f.id), Some(2), "should pick main FHD mp4");
    }

    #[test]
    fn falls_back_to_small_video_in_test_torrents() {
        let files = [FileCandidate {
            id: 0,
            path: Path::new("sample.mp4"),
            len: 512_000,
        }];
        let picked = select_video_file(&files);
        assert_eq!(
            picked.map(|f| f.id),
            Some(0),
            "should pick small test video"
        );
    }

    #[test]
    fn extracts_hash_from_magnet_and_bare() {
        let h = "581f855b36f4abf215d29e8758915f85a9d4698a";
        let magnet = format!(
            "magnet:?xt=urn:btih:{}&dn=SNOS-524&tr=udp://a",
            h.to_uppercase()
        );
        assert_eq!(
            extract_info_hash(&magnet),
            Some(h.to_string()),
            "from magnet"
        );
        assert_eq!(extract_info_hash(h), Some(h.to_string()), "from bare hash");
        assert_eq!(
            extract_info_hash("magnet:?xt=urn:btih:short"),
            None,
            "invalid hash"
        );
    }

    #[test]
    fn maps_video_mime_types() {
        assert_eq!(mime_for_path(Path::new("a.MP4")), "video/mp4", "mp4");
        assert_eq!(mime_for_path(Path::new("a.mkv")), "video/x-matroska", "mkv");
        assert_eq!(mime_for_path(Path::new("a.webm")), "video/webm", "webm");
    }
}
