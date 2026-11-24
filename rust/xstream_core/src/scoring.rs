//! Deterministic magnet candidate scoring shared by sync and search.
//!
//! Ported from `TitleSyncSink._score_magnet` in `scrapers/v2/sinks.py`.

/// Whether a magnet candidate originates from a curated HD source (`hhd800` / `+++`).
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash)]
#[non_exhaustive]
pub enum MagnetSource {
    /// Standard torrent upload.
    Standard,
    /// Curated `hhd800` / `+++` / `4k688` HD source (receives priority bonus).
    Hhd800,
}

/// Inputs required to score a single magnet candidate.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct MagnetMetrics<'a> {
    /// Resolution tag string (e.g. `"[FHD]"`, `"[4K]"`, `"720p"`, `""`).
    pub resolution: &'a str,
    /// Size label (e.g. `"9.4GB"`, `"2.2gb"`, `""`).
    pub size: &'a str,
    /// Reported seeder count.
    pub seed: i64,
    /// Whether the candidate is from a curated HD source.
    pub source: MagnetSource,
}

/// Priority bonus awarded to curated `hhd800` / `+++` HD releases.
const HHD800_BONUS: f64 = 1000.0;

/// Computes the deterministic ranking score for a magnet candidate.
///
/// Higher scores sort first. Resolution tiers check VR tags before generic
/// `"4k"` because `"[4KVR]"` contains `"4k"` as a substring.
pub fn score_magnet(metrics: &MagnetMetrics<'_>) -> f64 {
    let res = metrics.resolution;
    let res_score = if res.contains("[8KVR]") {
        700.0
    } else if res.contains("[4KVR]") {
        650.0
    } else if res.contains("[4K]") || res.to_lowercase().contains("4k") {
        600.0
    } else if res.contains("[FHDC]") {
        500.0
    } else if res.contains("[FHD]") {
        400.0
    } else if res.contains("1080p") {
        300.0
    } else if res.contains("[HD]") {
        200.0
    } else if res.contains("720p") {
        100.0
    } else {
        0.0
    };

    let size_mb = if metrics.size.is_empty() {
        0.0
    } else {
        let stripped = metrics.size.to_lowercase().replace("gb", "");
        stripped.trim().parse::<f64>().map_or(0.0, |gb| gb * 1024.0)
    };

    let hhd800_bonus = match metrics.source {
        MagnetSource::Hhd800 => HHD800_BONUS,
        MagnetSource::Standard => 0.0,
    };

    #[expect(
        clippy::as_conversions,
        clippy::cast_precision_loss,
        reason = "seeder counts are small integers well within exact f64 range"
    )]
    let seed_f = metrics.seed as f64;

    res_score + hhd800_bonus + seed_f + size_mb / 100.0
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn hd_selection_parity() {
        let hhd_fhd = MagnetMetrics {
            resolution: "[FHD]",
            size: "6.0GB",
            seed: 50,
            source: MagnetSource::Hhd800,
        };
        let vr_8k = MagnetMetrics {
            resolution: "[8KVR]",
            size: "12.0GB",
            seed: 10,
            source: MagnetSource::Standard,
        };
        let four_k = MagnetMetrics {
            resolution: "[4K]",
            size: "10.0GB",
            seed: 10,
            source: MagnetSource::Standard,
        };
        let plain_fhd = MagnetMetrics {
            resolution: "[FHD]",
            size: "6.0GB",
            seed: 50,
            source: MagnetSource::Standard,
        };

        assert!(score_magnet(&hhd_fhd) > score_magnet(&vr_8k));
        assert!(score_magnet(&vr_8k) > score_magnet(&four_k));
        assert!(score_magnet(&four_k) > score_magnet(&plain_fhd));
    }

    #[test]
    fn invalid_size_defaults_to_zero_mb() {
        let m = MagnetMetrics {
            resolution: "[HD]",
            size: "unknown",
            seed: 12,
            source: MagnetSource::Standard,
        };
        assert!((score_magnet(&m) - 212.0).abs() < f64::EPSILON);
    }
}
