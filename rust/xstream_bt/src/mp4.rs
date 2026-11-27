//! Pure ISO BMFF (MP4) top-level box scanner for exact on-demand `moov` discovery.
//!
//! Walking top-level boxes from the first 64 KiB of an MP4 file tells us whether
//! `moov` lives at the head (fast-start) or after `mdat` (tail-moov) and gives its
//! exact byte offset, eliminating fixed 10 MiB + 4 MiB guesswork.

/// Location of the MP4 `moov` atom discovered from top-level box headers.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
#[non_exhaustive]
pub enum MoovLocation {
    /// Fast-start MP4: `moov` precedes `mdat` and ends at `end_offset` (exclusive).
    Head {
        /// Exclusive byte offset where the `moov` box ends.
        end_offset: u64,
    },
    /// Tail-moov MP4: `mdat` precedes `moov`, which begins at `start_offset`.
    Tail {
        /// Inclusive byte offset where the `moov` box begins.
        start_offset: u64,
    },
    /// Non-MP4 container (MKV/TS/AVI) or insufficient header bytes.
    Unknown,
}

/// Inspect top-level ISO BMFF box headers in `head_bytes` for a file of `total_len` bytes.
///
/// Never panics on arbitrary untrusted byte sequences.
#[must_use]
pub fn inspect_mp4_head(head_bytes: &[u8], total_len: u64) -> MoovLocation {
    const MAX_BOXES: usize = 64;

    if head_bytes.len() < 12 || total_len < 16 {
        return MoovLocation::Unknown;
    }

    // Must start with an ISO BMFF `ftyp` box (or `wide`/`free` preceding `ftyp`).
    let first_type = &head_bytes[4..8];
    if first_type != b"ftyp" && first_type != b"free" && first_type != b"wide" {
        return MoovLocation::Unknown;
    }

    let mut offset: u64 = 0;
    let mut seen_ftyp = false;
    let mut iterations: usize = 0;

    while iterations < MAX_BOXES {
        iterations += 1;
        let Ok(pos) = usize::try_from(offset) else {
            break;
        };
        let Some(header) = head_bytes.get(pos..pos.saturating_add(8)) else {
            break;
        };
        let size32 = u32::from_be_bytes([header[0], header[1], header[2], header[3]]);
        let box_type = [header[4], header[5], header[6], header[7]];

        let box_size: u64 = match size32 {
            0 => total_len.saturating_sub(offset),
            1 => {
                let Some(ext) = head_bytes.get(pos.saturating_add(8)..pos.saturating_add(16))
                else {
                    break;
                };
                u64::from_be_bytes([
                    ext[0], ext[1], ext[2], ext[3], ext[4], ext[5], ext[6], ext[7],
                ])
            }
            n => u64::from(n),
        };

        let min_header = if size32 == 1 { 16 } else { 8 };
        if box_size < min_header {
            return MoovLocation::Unknown;
        }
        let Some(next_offset) = offset.checked_add(box_size) else {
            return MoovLocation::Unknown;
        };
        if next_offset > total_len {
            return MoovLocation::Unknown;
        }

        if &box_type == b"ftyp" {
            seen_ftyp = true;
        } else if &box_type == b"moov" {
            if seen_ftyp {
                return MoovLocation::Head {
                    end_offset: next_offset,
                };
            }
            return MoovLocation::Unknown;
        } else if &box_type == b"mdat" {
            if seen_ftyp && next_offset < total_len {
                // `mdat` ends before EOF -> `moov` lives at `next_offset..total_len`.
                return MoovLocation::Tail {
                    start_offset: next_offset,
                };
            }
            return MoovLocation::Unknown;
        }

        offset = next_offset;
        if offset >= total_len {
            break;
        }
    }

    MoovLocation::Unknown
}

#[cfg(test)]
mod tests {
    use proptest::prelude::*;

    use super::*;

    fn make_box(box_type: [u8; 4], payload_len: u32) -> Vec<u8> {
        let total = payload_len.saturating_add(8);
        let mut out = Vec::with_capacity(usize::try_from(total).unwrap_or(8));
        out.extend_from_slice(&total.to_be_bytes());
        out.extend_from_slice(&box_type);
        out.resize(usize::try_from(total).unwrap_or(8), 0);
        out
    }

    #[test]
    fn detects_fast_start_head_moov() {
        let mut buf = make_box(*b"ftyp", 16); // 24 bytes
        buf.extend_from_slice(&(2_000_000_u32).to_be_bytes());
        buf.extend_from_slice(b"moov");
        assert_eq!(
            inspect_mp4_head(&buf, 5_000_000_000),
            MoovLocation::Head {
                end_offset: 2_000_024
            },
            "fast-start moov end offset must equal ftyp + moov length"
        );
    }

    #[test]
    fn detects_tail_moov_with_64bit_mdat() {
        let mut buf = make_box(*b"ftyp", 16); // 24 bytes
        let mdat_len: u64 = 6_000_000_000;
        buf.extend_from_slice(&1_u32.to_be_bytes()); // 64-bit largesize sentinel
        buf.extend_from_slice(b"mdat");
        buf.extend_from_slice(&mdat_len.to_be_bytes());
        let total_len = 24 + mdat_len + 8_388_608;
        assert_eq!(
            inspect_mp4_head(&buf, total_len),
            MoovLocation::Tail {
                start_offset: 24 + mdat_len
            },
            "tail moov start offset must match end of 64-bit mdat"
        );
    }

    #[test]
    fn rejects_non_mp4_data() {
        let mkv = b"\x1a\x45\xdf\xa3some matroska bytes here";
        assert_eq!(
            inspect_mp4_head(mkv, 1_000_000),
            MoovLocation::Unknown,
            "non-MP4 header must return Unknown"
        );
    }

    proptest! {
        #[test]
        fn never_panics_on_arbitrary_bytes(
            data in proptest::collection::vec(any::<u8>(), 0..512),
            total_len in any::<u64>(),
        ) {
            let loc = inspect_mp4_head(&data, total_len);
            match loc {
                MoovLocation::Head { end_offset } => {
                    prop_assert!(end_offset <= total_len);
                }
                MoovLocation::Tail { start_offset } => {
                    prop_assert!(start_offset < total_len);
                }
                MoovLocation::Unknown => {}
            }
        }
    }
}
