"""In-process Okapi BM25 search index over the local xstream library.

Provides sub-5ms local title matching (code, title, star name, resolution)
with dash-insensitive code tokenization and CJK bigram/unigram support so
`/api/search` surfaces local library hits immediately and survives remote
catalog outages.
"""

from __future__ import annotations

import json
import math
import re
import time
from collections import Counter, defaultdict
from dataclasses import dataclass
from typing import Any

from core.db.connection import _conn as _db_conn

_ASCII_TOKEN_RE = re.compile(r"[a-z0-9]+")
_CJK_RUN_RE = re.compile(r"[\u3040-\u30ff\u3400-\u4dbf\u4e00-\u9fff]+")
_NON_ALNUM_RE = re.compile(r"[^a-z0-9]")

_INDEX_TTL_SECS = 120.0
_cached_index: tuple[float, LocalBm25Index] | None = None


def tokenize(text: str) -> list[str]:
    """Tokenize ASCII words, dash-stripped codes, and CJK unigrams + bigrams."""
    if not text:
        return []
    lower = text.lower()
    tokens: list[str] = []

    for m in _ASCII_TOKEN_RE.finditer(lower):
        tok = m.group(0)
        tokens.append(tok)

    # Also index contiguous alphanumeric code forms (e.g. "AEGE-042" -> "aege042")
    for part in lower.split():
        compact = _NON_ALNUM_RE.sub("", part)
        if len(compact) >= 4 and compact not in tokens:
            tokens.append(compact)

    # CJK runs: emit unigrams (for short names) and bigrams (for precision)
    for m in _CJK_RUN_RE.finditer(lower):
        run = m.group(0)
        if len(run) == 1:
            tokens.append(run)
        else:
            for i in range(len(run)):
                tokens.append(run[i])
                if i + 1 < len(run):
                    tokens.append(run[i : i + 2])
    return tokens


@dataclass(slots=True)
class LocalDoc:
    code: str
    norm_code: str
    title: str
    star_name: str
    star_code: str
    release_date: str | None
    views: int | None
    likes: int | None
    resolution: str
    magnet: str
    magnet_hash: str
    all_magnets: list[dict[str, Any]]
    doc_len: int


class LocalBm25Index:
    """Okapi BM25 (k1=1.5, b=0.75) inverted index over local library titles."""

    def __init__(self, docs: list[LocalDoc], k1: float = 1.5, b: float = 0.75) -> None:
        self.docs = docs
        self.k1 = k1
        self.b = b
        self.n_docs = len(docs)
        self.postings: dict[str, list[tuple[int, int]]] = defaultdict(list)
        self.idf: dict[str, float] = {}

        total_len = 0
        for idx, doc in enumerate(docs):
            # Weight code and star_name higher by repeating them in the indexed text.
            combined = f"{doc.code} {doc.code} {doc.norm_code} {doc.star_name} {doc.star_name} {doc.title} {doc.resolution}"
            toks = tokenize(combined)
            doc.doc_len = len(toks)
            total_len += doc.doc_len
            tf = Counter(toks)
            for term, freq in tf.items():
                self.postings[term].append((idx, freq))

        self.avg_dl = (total_len / self.n_docs) if self.n_docs else 1.0
        for term, plist in self.postings.items():
            df = len(plist)
            self.idf[term] = math.log((self.n_docs - df + 0.5) / (df + 0.5) + 1.0)

    def search(self, query: str, limit: int = 20) -> list[tuple[float, LocalDoc]]:
        """Return up to `limit` local documents ranked by BM25 + exact-code boost."""
        q_clean = query.strip()
        if not q_clean or self.n_docs == 0:
            return []
        q_terms = tokenize(q_clean)
        if not q_terms:
            return []
        q_norm = _NON_ALNUM_RE.sub("", q_clean.lower())

        scores: dict[int, float] = defaultdict(float)
        seen_terms = set(q_terms)
        for term in seen_terms:
            plist = self.postings.get(term)
            if not plist:
                continue
            idf = self.idf[term]
            for doc_idx, tf in plist:
                dl = self.docs[doc_idx].doc_len
                denom = tf + self.k1 * (1.0 - self.b + self.b * (dl / self.avg_dl))
                scores[doc_idx] += idf * (tf * (self.k1 + 1.0) / denom)

        # Boost exact or prefix code matches so explicit code queries always rank #1.
        if len(q_norm) >= 3:
            for doc_idx, doc in enumerate(self.docs):
                if doc.norm_code == q_norm:
                    scores[doc_idx] += 50.0
                elif doc.norm_code.startswith(q_norm):
                    scores[doc_idx] += 15.0

        ranked = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)[:limit]
        return [(score, self.docs[idx]) for idx, score in ranked if score > 0.0]


def invalidate_local_bm25() -> None:
    """Force the cached local BM25 index to rebuild on the next query."""
    global _cached_index
    _cached_index = None


def _build_index_from_db() -> LocalBm25Index:
    conn = _db_conn()
    try:
        rows = conn.execute(
            """
            SELECT code, title, star_name, star_code, release_date, views, likes,
                   resolution, magnet, magnet_hash, all_magnets
            FROM titles
            WHERE magnet IS NOT NULL AND magnet != '' AND dead_since IS NULL
            """
        ).fetchall()
    finally:
        conn.close()

    docs: list[LocalDoc] = []
    for r in rows:
        code = str(r[0] or "")
        raw_mags = r[10]
        if isinstance(raw_mags, str):
            try:
                raw_mags = json.loads(raw_mags)
            except (TypeError, ValueError):
                raw_mags = []
        mags = raw_mags if isinstance(raw_mags, list) else []
        docs.append(
            LocalDoc(
                code=code,
                norm_code=_NON_ALNUM_RE.sub("", code.lower()),
                title=str(r[1] or ""),
                star_name=str(r[2] or ""),
                star_code=str(r[3] or ""),
                release_date=r[4],
                views=r[5],
                likes=r[6],
                resolution=str(r[7] or ""),
                magnet=str(r[8] or ""),
                magnet_hash=str(r[9] or ""),
                all_magnets=mags,
                doc_len=0,
            )
        )
    return LocalBm25Index(docs)


def search_local_library(query: str, limit: int = 20) -> list[tuple[float, LocalDoc]]:
    """Query the TTL-cached local BM25 index (intended to run via `db_read`)."""
    global _cached_index
    now = time.monotonic()
    if _cached_index is None or (now - _cached_index[0]) >= _INDEX_TTL_SECS:
        _cached_index = (now, _build_index_from_db())
    return _cached_index[1].search(query, limit=limit)
