//! Magnet helpers and `sukebei.nyaa.si` RSS XML extractor.
//!
//! Ported from `scrapers/v2/extractors.py`. Uses `roxmltree` for zero-copy
//! XML parsing and preserves Python's insertion-ordered code grouping.

use std::collections::HashMap;
use std::fmt;
use std::sync::LazyLock;

use regex::Regex;

const NYAA_NS: &str = "https://sukebei.nyaa.si/xmlns/nyaa";

const SKIP_CODE_PREFIXES: [&str; 4] = ["OAE", "FWAY", "OF", "REBD"];

const MAGNET_TRACKERS: [&str; 5] = [
    "http://sukebei.tracker.wf:8888/announce",
    "udp://open.stealth.si:80/announce",
    "udp://tracker.opentrackr.org:1337/announce",
    "udp://exodus.desync.com:6969/announce",
    "udp://tracker.torrent.eu.org:451/announce",
];

const HD_UPLOADER_PREFIXES: [&str; 2] = ["+++ [fhd]", "+++ [fhdc]"];
const HD_SOURCE_MARKERS: [&str; 2] = ["hhd800", "4k688"];

static MAGNET_RE: LazyLock<Regex> = LazyLock::new(|| {
    Regex::new(r"^magnet:\?xt=urn:btih:[0-9a-fA-F]{40}([?&]|$)")
        .expect("MAGNET_RE is a valid static regex")
});

static LTX_RE: LazyLock<Regex> = LazyLock::new(|| {
    Regex::new(r"(?i)(?:\[LTX[^\]]*\]|\bLTX\b)").expect("LTX_RE is a valid static regex")
});

static CODE_RE: LazyLock<Regex> = LazyLock::new(|| {
    Regex::new(r"\b((?:[A-Z]|\d{3}[A-Z])[A-Z0-9]{0,7}-\d{2,5})\b")
        .expect("CODE_RE is a valid static regex")
});

static SIZE_RE: LazyLock<Regex> = LazyLock::new(|| {
    Regex::new(r"(?i)^([0-9.]+)\s*(GiB|MiB|TiB|GB|MB)").expect("SIZE_RE is a valid static regex")
});

static LEADING_TAGS_RE: LazyLock<Regex> = LazyLock::new(|| {
    Regex::new(r"^(\[[^\]]*\]\s*)+").expect("LEADING_TAGS_RE is a valid static regex")
});

static RFC822_DATE_RE: LazyLock<Regex> = LazyLock::new(|| {
    Regex::new(r"(?i)\b(\d{1,2})\s+(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+(\d{4})\b")
        .expect("RFC822_DATE_RE is a valid static regex")
});

/// Errors returned when parsing a Sukebei RSS document.
#[derive(Debug, Clone, PartialEq, Eq)]
#[non_exhaustive]
pub enum ParseRssError {
    /// The input XML was malformed or truncated.
    InvalidXml(String),
}

impl fmt::Display for ParseRssError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::InvalidXml(msg) => write!(f, "invalid rss xml: {msg}"),
        }
    }
}

impl std::error::Error for ParseRssError {}

/// Single magnet candidate parsed from an RSS `<item>`.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct RssMagnet {
    /// Full magnet URI with trackers.
    pub magnet: String,
    /// Normalized resolution tag (e.g. `"[FHD]"`, `"720p"`, `""`).
    pub resolution: String,
    /// Normalized size string (e.g. `"9.4GB"`, `""`).
    pub size: String,
    /// Reported seeder count.
    pub seed: i64,
    /// Reported leecher count.
    pub leech: i64,
    /// Whether the upload comes from a curated HD release group.
    pub is_hhd800: bool,
}

/// Grouped work item parsed from a Sukebei RSS feed.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct RssWork {
    /// Uppercase work code (e.g. `"SNOS-524"`).
    pub code: String,
    /// Cleaned title with code and leading `[tag]` prefixes stripped.
    pub title: String,
    /// Release date formatted as `dd/mm/YYYY`, if parseable.
    pub release_date: Option<String>,
    /// Maximum download count across grouped torrents (`None` when zero).
    pub likes: Option<i64>,
    /// All magnet candidates belonging to this code.
    pub magnets: Vec<RssMagnet>,
}

/// HTML-unescapes common magnet URI entities, up to 3 passes for double-escaped
/// sources like `&amp;amp;dn=`.
pub fn unescape_magnet(magnet_url: &str) -> String {
    let mut current = magnet_url.to_owned();
    for _ in 0..3 {
        let next = unescape_html_basic(&current);
        if next == current {
            break;
        }
        current = next;
    }
    current
}

fn unescape_html_basic(s: &str) -> String {
    if !s.contains('&') {
        return s.to_owned();
    }
    s.replace("&amp;", "&")
        .replace("&lt;", "<")
        .replace("&gt;", ">")
        .replace("&quot;", "\"")
        .replace("&#39;", "'")
        .replace("&#x27;", "'")
        .replace("&#x2F;", "/")
        .replace("&#47;", "/")
}

/// Returns `true` if `magnet_url` is a valid v1 `btih` magnet with a 40-hex-char
/// hash and no leftover `&amp;` entity.
pub fn is_valid_magnet(magnet_url: &str) -> bool {
    MAGNET_RE.is_match(magnet_url) && !magnet_url.contains("&amp;")
}

/// Returns `true` if `text` denotes an LTX mosaic-removal release.
pub fn is_ltx(text: &str) -> bool {
    !text.is_empty() && LTX_RE.is_match(text)
}

/// Returns `true` if a magnet row or torrent title originates from a curated HD group.
pub fn is_hd_source(raw_text: &str, dn_or_title: &str) -> bool {
    let raw_l = raw_text.to_lowercase();
    let dn_l = dn_or_title.trim_start().to_lowercase();
    if HD_SOURCE_MARKERS
        .iter()
        .any(|m| raw_l.contains(m) || dn_l.contains(m))
    {
        return true;
    }
    HD_UPLOADER_PREFIXES
        .iter()
        .any(|prefix| dn_l.starts_with(prefix))
}

/// Maps resolution hints in a torrent title to the vocabulary `score_magnet` expects.
pub fn parse_resolution_tag(title: &str) -> &'static str {
    let upper = title.to_uppercase();
    if upper.contains("8KVR") {
        "[8KVR]"
    } else if upper.contains("4KVR") {
        "[4KVR]"
    } else if upper.contains("4K") || upper.contains("2160P") {
        "[4K]"
    } else if upper.contains("[FHDC]") {
        "[FHDC]"
    } else if upper.contains("[FHD]") {
        "[FHD]"
    } else if upper.contains("1080P") {
        "1080p"
    } else if upper.contains("[HD]") {
        "[HD]"
    } else if upper.contains("720P") {
        "720p"
    } else {
        ""
    }
}

/// Converts nyaa size strings like `"3.6 GiB"` / `"800.0 MiB"` to `"X.XGB"`.
pub fn size_to_gb(size: &str) -> String {
    let Some(caps) = SIZE_RE.captures(size.trim()) else {
        return String::new();
    };
    let Ok(mut value) = caps[1].parse::<f64>() else {
        return String::new();
    };
    match caps[2].to_lowercase().as_str() {
        "tib" => value *= 1024.0,
        "mib" => value /= 1024.0,
        _ => {}
    }
    format!("{value:.1}GB")
}

#[derive(Clone, Copy)]
enum SlashEncoding {
    Keep,
    Encode,
}

/// Percent-encodes a UTF-8 string matching Python's `urllib.parse.quote`.
fn percent_encode(input: &str, slash: SlashEncoding) -> String {
    let mut out = String::with_capacity(input.len());
    for byte in input.as_bytes() {
        let keep_slash = matches!(slash, SlashEncoding::Keep) && *byte == b'/';
        let is_unreserved = byte.is_ascii_alphanumeric()
            || matches!(*byte, b'-' | b'.' | b'_' | b'~')
            || keep_slash;
        if is_unreserved {
            out.push(char::from(*byte));
        } else {
            use std::fmt::Write;
            let _ = write!(out, "%{byte:02X}");
        }
    }
    out
}

/// Constructs a magnet URI from a 40-hex info hash and display title.
pub fn build_magnet(info_hash: &str, title: &str) -> String {
    use std::fmt::Write;
    let mut magnet = format!(
        "magnet:?xt=urn:btih:{}&dn={}",
        info_hash.to_lowercase(),
        percent_encode(title, SlashEncoding::Keep)
    );
    for tr in MAGNET_TRACKERS {
        let _ = write!(magnet, "&tr={}", percent_encode(tr, SlashEncoding::Encode));
    }
    magnet
}

/// Converts an RFC 822 `pubDate` string to `dd/mm/YYYY`.
pub fn pubdate_to_release(pubdate: &str) -> Option<String> {
    let caps = RFC822_DATE_RE.captures(pubdate)?;
    let day: u32 = caps[1].parse().ok()?;
    let year: u32 = caps[3].parse().ok()?;
    let month: u32 = match caps[2].to_lowercase().as_str() {
        "jan" => 1,
        "feb" => 2,
        "mar" => 3,
        "apr" => 4,
        "may" => 5,
        "jun" => 6,
        "jul" => 7,
        "aug" => 8,
        "sep" => 9,
        "oct" => 10,
        "nov" => 11,
        "dec" => 12,
        _ => return None,
    };
    Some(format!("{day:02}/{month:02}/{year:04}"))
}

fn is_valid_hex40(s: &str) -> bool {
    s.len() == 40 && s.bytes().all(|b| b.is_ascii_hexdigit())
}

fn child_text<'a>(node: roxmltree::Node<'a, 'a>, tag: &str, ns: Option<&str>) -> &'a str {
    node.children()
        .find(|n| n.is_element() && n.tag_name().name() == tag && n.tag_name().namespace() == ns)
        .and_then(|n| n.text())
        .unwrap_or("")
}

/// Parses a `sukebei.nyaa.si` RSS XML response into grouped [`RssWork`] entries.
///
/// # Errors
///
/// Returns [`ParseRssError::InvalidXml`] if `rss_xml` is not well-formed XML.
pub fn parse_sukebei_rss(
    rss_xml: &str,
    star_names: &[&str],
) -> Result<Vec<RssWork>, ParseRssError> {
    let doc = roxmltree::Document::parse(rss_xml)
        .map_err(|err| ParseRssError::InvalidXml(err.to_string()))?;

    let names_ci: Vec<String> = star_names
        .iter()
        .filter(|n| !n.is_empty())
        .map(|n| n.to_lowercase())
        .collect();

    let mut order: Vec<String> = Vec::new();
    let mut grouped: HashMap<String, (String, Vec<RssMagnet>, i64, Option<String>)> =
        HashMap::new();

    for node in doc
        .descendants()
        .filter(|n| n.is_element() && n.tag_name().name() == "item")
    {
        let title = child_text(node, "title", None);
        if is_ltx(title) {
            continue;
        }
        let title_lower = title.to_lowercase();
        if !names_ci.is_empty() && !names_ci.iter().any(|n| title_lower.contains(n)) {
            continue;
        }
        let Some(caps) = CODE_RE.captures(title) else {
            continue;
        };
        let code = caps[1].to_uppercase();
        if SKIP_CODE_PREFIXES.iter().any(|p| code.starts_with(p)) {
            continue;
        }

        let info_hash = child_text(node, "infoHash", Some(NYAA_NS));
        if !is_valid_hex40(info_hash) {
            continue;
        }

        let seed = child_text(node, "seeders", Some(NYAA_NS))
            .trim()
            .parse::<i64>()
            .unwrap_or(0);
        let leech = child_text(node, "leechers", Some(NYAA_NS))
            .trim()
            .parse::<i64>()
            .unwrap_or(0);
        let downloads = child_text(node, "downloads", Some(NYAA_NS))
            .trim()
            .parse::<i64>()
            .unwrap_or(0);
        let size = size_to_gb(child_text(node, "size", Some(NYAA_NS)));
        let resolution = parse_resolution_tag(title).to_owned();
        let release = pubdate_to_release(child_text(node, "pubDate", None));
        let is_hhd800 = is_hd_source(title, title);

        let candidate = RssMagnet {
            magnet: build_magnet(info_hash, title),
            resolution,
            size,
            seed,
            leech,
            is_hhd800,
        };

        let entry = grouped.entry(code.clone()).or_insert_with(|| {
            order.push(code);
            (title.to_owned(), Vec::new(), 0, None)
        });
        entry.1.push(candidate);
        if downloads > entry.2 {
            entry.2 = downloads;
        }
        if let Some(rel) = release {
            let should_replace = match entry.3.as_deref() {
                None => true,
                Some(cur) => rel.as_str() > cur,
            };
            if should_replace {
                entry.3 = Some(rel);
            }
        }
    }

    let mut works = Vec::with_capacity(order.len());
    for code in order {
        if let Some((raw_title, magnets, downloads, release_date)) = grouped.remove(&code) {
            let without_code = CODE_RE.replace(&raw_title, "");
            let trimmed = without_code.trim();
            let clean_title = LEADING_TAGS_RE.replace(trimmed, "").trim().to_owned();
            works.push(RssWork {
                code,
                title: clean_title,
                release_date,
                likes: if downloads > 0 { Some(downloads) } else { None },
                magnets,
            });
        }
    }

    Ok(works)
}

#[cfg(test)]
mod tests {
    use super::*;

    fn rss_item(title: &str, hash: &str, seeders: i64, size: &str) -> String {
        format!(
            "<item><title>{title}</title>\
             <pubDate>Tue, 28 Jul 2026 14:15:28 -0000</pubDate>\
             <nyaa:seeders>{seeders}</nyaa:seeders>\
             <nyaa:leechers>2</nyaa:leechers>\
             <nyaa:downloads>100</nyaa:downloads>\
             <nyaa:infoHash>{hash}</nyaa:infoHash>\
             <nyaa:size>{size}</nyaa:size></item>"
        )
    }

    fn rss_doc(items: &str) -> String {
        format!(
            "<rss xmlns:nyaa=\"https://sukebei.nyaa.si/xmlns/nyaa\" version=\"2.0\">\
             <channel>{items}</channel></rss>"
        )
    }

    #[test]
    fn unescapes_double_escaped_magnet_and_validates() {
        let raw = "magnet:?xt=urn:btih:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa&amp;amp;dn=Test";
        let unescaped = unescape_magnet(raw);
        assert_eq!(
            unescaped,
            "magnet:?xt=urn:btih:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa&dn=Test"
        );
        assert!(is_valid_magnet(&unescaped));
        assert!(!is_valid_magnet("magnet:?xt=urn:btih:short"));
    }

    #[test]
    fn groups_multiple_torrents_per_code_and_drops_ltx() {
        let h1 = "11".repeat(20);
        let h2 = "22".repeat(20);
        let h3 = "33".repeat(20);
        let xml = rss_doc(&format!(
            "{}{}{}",
            rss_item("+++ [LTX] SNOS-524 Hina Yukino", &h1, 200, "4.5 GiB"),
            rss_item("[HD] SNOS-524 Hina Yukino", &h2, 20, "9.5 GiB"),
            rss_item("+++ [FHD] SNOS-524 Hina Yukino", &h3, 224, "9.4 GiB"),
        ));

        let works = parse_sukebei_rss(&xml, &[]).unwrap();
        assert_eq!(works.len(), 1);
        assert_eq!(works[0].code, "SNOS-524");
        assert_eq!(works[0].magnets.len(), 2);
        assert_eq!(works[0].release_date.as_deref(), Some("28/07/2026"));
        assert!(works[0].magnets[1].is_hhd800);
        assert_eq!(works[0].magnets[1].resolution, "[FHD]");
        assert_eq!(works[0].magnets[1].size, "9.4GB");
    }

    #[test]
    fn filters_by_star_name_and_skips_blacklisted_prefixes() {
        let h1 = "aa".repeat(20);
        let h2 = "bb".repeat(20);
        let h3 = "cc".repeat(20);
        let xml = rss_doc(&format!(
            "{}{}{}",
            rss_item("OAE-100 Miru image video", &h1, 10, "3.0 GiB"),
            rss_item("SONE-100 Other Star", &h2, 10, "3.0 GiB"),
            rss_item("229SCUTE-1575 Miru debut", &h3, 15, "800.0 MiB"),
        ));

        let works = parse_sukebei_rss(&xml, &["miru"]).unwrap();
        assert_eq!(works.len(), 1);
        assert_eq!(works[0].code, "229SCUTE-1575");
        assert_eq!(works[0].magnets[0].size, "0.8GB");
    }

    #[test]
    fn parses_vr_resolution_before_plain_4k() {
        assert_eq!(parse_resolution_tag("[8KVR] SIVR-100"), "[8KVR]");
        assert_eq!(parse_resolution_tag("[4KVR] SIVR-101"), "[4KVR]");
        assert_eq!(parse_resolution_tag("[4K] SONE-100"), "[4K]");
    }
}
