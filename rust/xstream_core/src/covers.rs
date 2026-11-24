//! Fast filesystem cover-index scanner for `/api/stars`.
//!
//! Ported from `_scan_cover_files` in `backend/routers/stars.py`. Scans
//! `images/titles/<code>/` and reports `(has_full, has_thumb, has_mid)` per
//! uppercase title code so `/api/stars` can emit direct static Caddy URLs
//! without per-title `/api/cover` 307 redirects.

use std::collections::HashMap;
use std::fs;
use std::path::Path;

/// Availability flags for exported cover files of a single title.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Default)]
pub struct CoverPresence {
    /// Full-resolution `<code>.jpg` exists on disk.
    pub has_full: bool,
    /// Thumbnail `<code>_thumb.jpg` exists on disk.
    pub has_thumb: bool,
    /// Medium `<code>_mid.jpg` exists on disk.
    pub has_mid: bool,
}

/// Scans `titles_dir` (`images/titles/`) and returns a map of uppercase title
/// code to [`CoverPresence`].
///
/// Unreadable subdirectories or a missing root directory are skipped quietly,
/// matching the original Python implementation.
pub fn scan_cover_files(titles_dir: &Path) -> HashMap<String, CoverPresence> {
    let Ok(entries) = fs::read_dir(titles_dir) else {
        return HashMap::new();
    };

    let mut index = HashMap::new();
    for entry in entries.flatten() {
        let Ok(file_type) = entry.file_type() else {
            continue;
        };
        if !file_type.is_dir() {
            continue;
        }
        let Ok(code_dir) = entry.file_name().into_string() else {
            continue;
        };
        let Ok(sub_entries) = fs::read_dir(entry.path()) else {
            continue;
        };

        let full_name = format!("{code_dir}.jpg");
        let thumb_name = format!("{code_dir}_thumb.jpg");
        let mid_name = format!("{code_dir}_mid.jpg");

        let mut presence = CoverPresence::default();
        for sub in sub_entries.flatten() {
            let name = sub.file_name();
            if name == full_name.as_str() {
                presence.has_full = true;
            } else if name == thumb_name.as_str() {
                presence.has_thumb = true;
            } else if name == mid_name.as_str() {
                presence.has_mid = true;
            }
            if presence.has_full && presence.has_thumb && presence.has_mid {
                break;
            }
        }
        index.insert(code_dir.to_uppercase(), presence);
    }
    index
}

#[cfg(test)]
mod tests {
    use std::fs::File;
    use std::time::{SystemTime, UNIX_EPOCH};

    use super::*;

    fn temp_dir(label: &str) -> std::path::PathBuf {
        let nanos = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .expect("system clock after epoch")
            .as_nanos();
        let dir = std::env::temp_dir().join(format!("xstream_covers_{label}_{nanos}"));
        fs::create_dir_all(&dir).expect("create temp dir");
        dir
    }

    #[test]
    fn scans_full_thumb_and_mid_files() {
        let root = temp_dir("basic");
        let d1 = root.join("snos-524");
        let d2 = root.join("abc-001");
        fs::create_dir_all(&d1).unwrap();
        fs::create_dir_all(&d2).unwrap();
        File::create(d1.join("snos-524.jpg")).unwrap();
        File::create(d1.join("snos-524_thumb.jpg")).unwrap();
        File::create(d1.join("snos-524_mid.jpg")).unwrap();
        File::create(d2.join("abc-001.jpg")).unwrap();

        let idx = scan_cover_files(&root);
        assert_eq!(
            idx.get("SNOS-524"),
            Some(&CoverPresence {
                has_full: true,
                has_thumb: true,
                has_mid: true,
            })
        );
        assert_eq!(
            idx.get("ABC-001"),
            Some(&CoverPresence {
                has_full: true,
                has_thumb: false,
                has_mid: false,
            })
        );
        let _ = fs::remove_dir_all(&root);
    }

    #[test]
    fn missing_root_returns_empty_map() {
        let idx = scan_cover_files(Path::new("/nonexistent/xstream/titles/dir"));
        assert_eq!(idx.len(), 0);
    }
}
