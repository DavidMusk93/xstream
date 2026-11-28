"""Unit tests for in-process Okapi BM25 local library search."""

from __future__ import annotations

from backend.services.local_bm25 import LocalBm25Index, LocalDoc, tokenize


def _doc(code: str, title: str, star: str, res: str = "[FHD]") -> LocalDoc:
    return LocalDoc(
        code=code,
        norm_code=code.replace("-", "").lower(),
        title=title,
        star_name=star,
        star_code=star.lower(),
        release_date="01/01/2026",
        views=100,
        likes=10,
        resolution=res,
        magnet=f"magnet:?xt=urn:btih:{'a' * 40}",
        magnet_hash="a" * 40,
        all_magnets=[],
        doc_len=0,
    )


def test_bm25_ranks_exact_code_and_star_matches() -> None:
    idx = LocalBm25Index([
        _doc("AEGE-042", "Big-breasted Young Wife Kept As A Pet", "Kokona Asakura"),
        _doc("MIDA-912", "4K Special Release", "Mio Ishikawa", "[4K]"),
        _doc("CAWB-076", "朝倉ここな 温泉旅行", "朝倉ここな"),
    ])

    # Dash-insensitive exact code match ranks first
    res = idx.search("aege042")
    assert res and res[0][1].code == "AEGE-042"

    # English star/title keyword search
    res2 = idx.search("Kokona Pet")
    assert res2 and res2[0][1].code == "AEGE-042"

    # CJK bigram/unigram search
    res3 = idx.search("温泉旅行")
    assert res3 and res3[0][1].code == "CAWB-076"

    # No match returns empty
    assert idx.search("zzzzzz-999") == []


def test_tokenize_handles_codes_and_cjk() -> None:
    toks = tokenize("AEGE-042 温泉")
    assert "aege" in toks
    assert "042" in toks
    assert "aege042" in toks
    assert "温泉" in toks
