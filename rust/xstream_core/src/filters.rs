//! Collection-stage visibility filter for scraped video items.
//!
//! Ported from `scrapers/v2/filters.py`. Decides whether a title should be
//! excluded from the library (VR works, multi-star/omnibus works, cast lists,
//! or titles mentioning another rostered star).

use std::collections::HashSet;
use std::fmt;
use std::sync::LazyLock;

use regex::Regex;

/// Minimum character length for a roster name to trigger substring matching.
const MIN_NAME_LEN: usize = 3;

static VR_TITLE_RE: LazyLock<Regex> = LazyLock::new(|| {
    Regex::new(r"(?i)(【VR】|\[VR\])").expect("VR_TITLE_RE is a valid static regex")
});

static VR_CODE_RE: LazyLock<Regex> = LazyLock::new(|| {
    Regex::new(
        r"(?i)^(SIVR|KAVR|DSVR|FAVR|PXVR|AJVR|MDVR|SAVR|TMAVR|VRKM|IPVR|KIWVR|NHVR|PRVR|BIBIVR|CRVR|URVRSP|EBVR|HNVR)[-0-9]",
    )
    .expect("VR_CODE_RE is a valid static regex")
});

static MULTI_KEYWORD_RE: LazyLock<Regex> = LazyLock::new(|| {
    Regex::new(r"共演|オムニバス").expect("MULTI_KEYWORD_RE is a valid static regex")
});

static COLON_CAST_RE: LazyLock<Regex> = LazyLock::new(|| {
    Regex::new(r"[:：]\s*(?:[A-Z][a-z]+ [A-Z][a-z]+,\s*)+[A-Z][a-z]+ [A-Z][a-z]+")
        .expect("COLON_CAST_RE is a valid static regex")
});

static WHOLE_CAST_RE: LazyLock<Regex> = LazyLock::new(|| {
    Regex::new(r"^(?:[A-Z][a-z]+ [A-Z][a-z]+,\s*){2,}[A-Z][a-z]+ [A-Z][a-z]+\.?\s*$")
        .expect("WHOLE_CAST_RE is a valid static regex")
});

static JP_CAST_RE: LazyLock<Regex> = LazyLock::new(|| {
    Regex::new(r"(?:[\u{4e00}-\u{9fa5}]{2,4}[、\s]){2,}[\u{4e00}-\u{9fa5}]{2,4}")
        .expect("JP_CAST_RE is a valid static regex")
});

/// Reason a scraped title is excluded from the library.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash)]
#[non_exhaustive]
pub enum HiddenReason {
    /// Card lists more than one actress link.
    StarCount,
    /// VR title, VR label prefix, or VR magnet resolution tag.
    Vr,
    /// Multi-star / omnibus Japanese keyword in title.
    Keyword,
    /// Title mentions another rostered star (excluding the star's own aliases).
    Roster,
    /// Title contains a multi-name Latin or Japanese cast list.
    Cast,
}

impl HiddenReason {
    /// Returns the canonical string tag matching Python's `hidden_reason()`.
    pub fn as_str(self) -> &'static str {
        match self {
            Self::StarCount => "star_count",
            Self::Vr => "vr",
            Self::Keyword => "keyword",
            Self::Roster => "roster",
            Self::Cast => "cast",
        }
    }
}

impl fmt::Display for HiddenReason {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str(self.as_str())
    }
}

/// Minimal view of a scraped title needed by [`hidden_reason`].
#[derive(Debug, Clone, Copy)]
pub struct FilterInput<'a> {
    /// Title code (e.g. `"SNOS-524"`).
    pub code: &'a str,
    /// Title text.
    pub title: &'a str,
    /// Number of actress links found on the card (`0` when unknown).
    pub star_count: usize,
    /// Resolution strings of all magnet candidates on this title.
    pub magnet_resolutions: &'a [&'a str],
}

/// Returns why a title must not enter the library, or `None` to keep it.
///
/// `own_names` (the synced star's English/Japanese aliases) are excluded from
/// the roster mention check because uploaders routinely tag torrents with the
/// star's own name.
pub fn hidden_reason(
    input: &FilterInput<'_>,
    own_names: &[&str],
    roster_names: &[&str],
) -> Option<HiddenReason> {
    if input.star_count > 1 {
        return Some(HiddenReason::StarCount);
    }

    let text = input.title.trim();
    if !text.is_empty() && VR_TITLE_RE.is_match(text) {
        return Some(HiddenReason::Vr);
    }
    if VR_CODE_RE.is_match(input.code) {
        return Some(HiddenReason::Vr);
    }
    if input
        .magnet_resolutions
        .iter()
        .any(|res| res.to_lowercase().contains("vr"))
    {
        return Some(HiddenReason::Vr);
    }
    if text.is_empty() {
        return None;
    }

    if MULTI_KEYWORD_RE.is_match(text) {
        return Some(HiddenReason::Keyword);
    }

    let lower = text.to_lowercase();
    let own: HashSet<String> = own_names.iter().map(|n| n.trim().to_lowercase()).collect();
    for name in roster_names {
        let nl = name.trim().to_lowercase();
        if nl.chars().count() >= MIN_NAME_LEN && !own.contains(&nl) && lower.contains(&nl) {
            return Some(HiddenReason::Roster);
        }
    }

    if COLON_CAST_RE.is_match(text) || WHOLE_CAST_RE.is_match(text) || JP_CAST_RE.is_match(text) {
        return Some(HiddenReason::Cast);
    }

    None
}

#[cfg(test)]
mod tests {
    use super::*;

    fn item<'a>(
        code: &'a str,
        title: &'a str,
        star_count: usize,
        resolutions: &'a [&'a str],
    ) -> FilterInput<'a> {
        FilterInput {
            code,
            title,
            star_count,
            magnet_resolutions: resolutions,
        }
    }

    #[test]
    fn drops_vr_title() {
        let it = item("SONE-001", "【VR】Special Edition", 1, &[]);
        assert_eq!(hidden_reason(&it, &[], &[]), Some(HiddenReason::Vr));
    }

    #[test]
    fn drops_vr_resolution_tag() {
        let it = item("SONE-001", "Normal Title", 1, &["[8KVR]"]);
        assert_eq!(hidden_reason(&it, &[], &[]), Some(HiddenReason::Vr));
    }

    #[test]
    fn drops_vr_label_prefix() {
        let it = item("SIVR-310", "", 0, &[]);
        assert_eq!(hidden_reason(&it, &[], &[]), Some(HiddenReason::Vr));
    }

    #[test]
    fn drops_multi_star_count() {
        let it = item("MIRD-282", "Solo looking title", 3, &[]);
        assert_eq!(hidden_reason(&it, &[], &[]), Some(HiddenReason::StarCount));
    }

    #[test]
    fn drops_multi_star_keyword() {
        let it = item("MIRD-282", "豪華共演スペシャル", 0, &[]);
        assert_eq!(hidden_reason(&it, &[], &[]), Some(HiddenReason::Keyword));
    }

    #[test]
    fn drops_cast_list() {
        let it = item(
            "MIRD-282",
            "Best Of: Alice Smith, Bob Jones, Carol White",
            0,
            &[],
        );
        assert_eq!(hidden_reason(&it, &[], &[]), Some(HiddenReason::Cast));

        let jp = item("MIRD-283", "三上悠亜、橋本有菜、天使萌", 0, &[]);
        assert_eq!(hidden_reason(&jp, &[], &[]), Some(HiddenReason::Cast));
    }

    #[test]
    fn drops_other_roster_star_mention() {
        let it = item("SONE-100", "Special with Yuka Murakami", 0, &[]);
        assert_eq!(
            hidden_reason(&it, &["miru"], &["miru", "Yuka Murakami"]),
            Some(HiddenReason::Roster)
        );
    }

    #[test]
    fn keeps_own_name_mention() {
        let it = item("SONE-100", "Solo work by miru", 1, &["[FHD]"]);
        assert_eq!(
            hidden_reason(&it, &["miru"], &["miru", "Yuka Murakami"]),
            None
        );
    }

    #[test]
    fn keeps_plain_solo() {
        let it = item("SNOS-524", "Newcomer No. 1 Style Debut", 1, &["[FHD]"]);
        assert_eq!(hidden_reason(&it, &["Hina Yukino"], &["Hina Yukino"]), None);
    }
}
