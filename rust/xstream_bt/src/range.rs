//! HTTP `Range` header parser for single-range byte requests (RFC 9110).

/// Inclusive byte range `[start, end]` within a resource of known size.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct ByteRange {
    /// First byte offset (inclusive).
    pub start: u64,
    /// Last byte offset (inclusive).
    pub end: u64,
}

impl ByteRange {
    /// Number of bytes covered by this inclusive range.
    pub const fn len(self) -> u64 {
        self.end - self.start + 1
    }

    /// Always false for a validated [`ByteRange`], included for clippy `len_without_is_empty`.
    pub const fn is_empty(self) -> bool {
        self.end < self.start
    }
}

/// Parse an HTTP `Range` header value against `total_size`.
///
/// Supports:
/// - `bytes=start-end`
/// - `bytes=start-`
/// - `bytes=-suffix`
///
/// Returns `None` if `total_size == 0`, the unit is not `bytes=`, the range is
/// malformed, multi-range, or out of bounds.
pub fn parse_byte_range(header: &str, total_size: u64) -> Option<ByteRange> {
    if total_size == 0 {
        return None;
    }
    let spec = header.trim().strip_prefix("bytes=")?;
    if spec.contains(',') {
        return None;
    }
    let (raw_start, raw_end) = spec.split_once('-')?;
    let raw_start = raw_start.trim();
    let raw_end = raw_end.trim();

    let (start, end) = match (raw_start.is_empty(), raw_end.is_empty()) {
        (false, false) => {
            let start = raw_start.parse::<u64>().ok()?;
            let end = raw_end.parse::<u64>().ok()?;
            if start >= total_size || start > end {
                return None;
            }
            // RFC 9110 §14.1.2: clamp end to last byte if client asks past EOF.
            (start, end.min(total_size - 1))
        }
        (false, true) => {
            let start = raw_start.parse::<u64>().ok()?;
            if start >= total_size {
                return None;
            }
            (start, total_size - 1)
        }
        (true, false) => {
            let suffix = raw_end.parse::<u64>().ok()?;
            if suffix == 0 {
                return None;
            }
            let clamped = suffix.min(total_size);
            (total_size - clamped, total_size - 1)
        }
        (true, true) => return None,
    };

    Some(ByteRange { start, end })
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn parses_standard_range() {
        let r = parse_byte_range("bytes=0-1023", 4096);
        assert_eq!(
            r,
            Some(ByteRange {
                start: 0,
                end: 1023
            }),
            "standard range"
        );
        assert_eq!(r.map(ByteRange::len), Some(1024), "range length");
    }

    #[test]
    fn parses_open_ended_range() {
        let r = parse_byte_range("bytes=1000-", 4096);
        assert_eq!(
            r,
            Some(ByteRange {
                start: 1000,
                end: 4095
            }),
            "open-ended"
        );
    }

    #[test]
    fn parses_suffix_range() {
        let r = parse_byte_range("bytes=-500", 4096);
        assert_eq!(
            r,
            Some(ByteRange {
                start: 3596,
                end: 4095
            }),
            "suffix"
        );
        let full = parse_byte_range("bytes=-99999", 4096);
        assert_eq!(
            full,
            Some(ByteRange {
                start: 0,
                end: 4095
            }),
            "clamped suffix"
        );
    }

    #[test]
    fn clamps_end_past_eof() {
        let r = parse_byte_range("bytes=4000-9999", 4096);
        assert_eq!(
            r,
            Some(ByteRange {
                start: 4000,
                end: 4095
            }),
            "clamped end"
        );
    }

    #[test]
    fn rejects_invalid_ranges() {
        assert_eq!(parse_byte_range("bytes=4096-", 4096), None, "start at eof");
        assert_eq!(parse_byte_range("bytes=500-100", 4096), None, "reversed");
        assert_eq!(parse_byte_range("bytes=-0", 4096), None, "zero suffix");
        assert_eq!(parse_byte_range("items=0-10", 4096), None, "wrong unit");
        assert_eq!(
            parse_byte_range("bytes=0-10, 20-30", 4096),
            None,
            "multi-range"
        );
        assert_eq!(parse_byte_range("bytes=0-0", 0), None, "empty file");
    }
}
