"""backend/routers/search.py — ijavtorrent catalog search

Searches the ijavtorrent catalog (`/?searchTerm=` endpoint — the older
`/?s=` param silently returns the homepage since the 2026-09 redesign) and
returns work cards enriched with local state: in-library flag and
per-actress followed flag.

Keyword queries apply the same collection-stage filters as the sync
pipeline (scrapers/v2/filters.py), so VR / multi-star works stay
consistent with what a follow would actually import. Code-like queries
are exact-match lookups: the user explicitly asked for that work, so
filters are skipped and, when ijavtorrent has no match (its catalog has
been sparse since the 2026-08 loss), we fall back to the sukebei RSS
source — the same hybrid pattern as sync. sukebei items carry no cover
or actress links, so no follow button can be offered for them.

Name queries also hit ijavtorrent's server-side actress directory search
(`/actresses?searchTerm=`), so an actress is followable (with her profile
image) even when the video search returns nothing for the name; the
offline-crawled local index (data/actress_index.json) is the fallback.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
import time
import urllib.parse
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import RedirectResponse, Response
from pydantic import BaseModel

from backend.routers.auth import require_auth
from backend.routers.stars import _load_config
from core import get_logger
from core.db.connection import _conn as _db_conn
from core.db.write_queue import db_read
from scrapers.v2.extractors import (
    IJAV_BASE_URL,
    IJavTorrentExtractor,
    SukebeiRssExtractor,
    normalize_actress_url,
    parse_actress_directory,
)
from scrapers.v2.filters import hidden_reason
from scrapers.v2.schemas import VideoItem
from scrapers.v2.sinks import TitleSyncSink
from scrapers.v2.tasks.sync_titles import SUKEBEI_RSS_URL

log = get_logger("search-router")
router = APIRouter(prefix="/api/search", tags=["search"], dependencies=[Depends(require_auth)])

# In-memory TTL cache for the remote fetch + filter stage (the expensive
# part). Local enrichment (in_library / followed) runs per request so a
# follow or sync is reflected immediately.
_CACHE_TTL = 60.0
_items_cache: dict[str, tuple[float, list[tuple[VideoItem, str]], list[dict]]] = {}

# Code-like query: "SSIS-123", "ssis123", "229SCUTE-1575". WordPress search
# is fuzzy full-text, so for code-like queries we keep only exact code
# matches (dash-insensitive); keyword queries pass through in ijav's order.
_CODE_QUERY_RE = re.compile(r"^[A-Za-z0-9]{2,10}-?\d{2,5}$")


class SearchResultStar(BaseModel):
    name: str
    url: str
    code: str = ""  # library code when followed — lets the UI jump to her shelf
    followed: bool = False


class SearchResultActress(SearchResultStar):
    """Directory match from ijavtorrent's actress search (or the local
    actress index fallback) — followable even when the video search
    returns nothing for the name."""

    image: str = ""


class SearchResultMagnet(BaseModel):
    magnet: str
    resolution: str = ""
    size: str = ""
    seeds: int = 0
    is_hd: bool = False  # hhd800.com high-quality source


class SearchResultItem(BaseModel):
    code: str
    title: str = ""
    release_date: str | None = None
    views: int | None = None
    likes: int | None = None
    cover_url: str | None = None
    resolution: str = ""
    size: str = ""
    seeds: int = 0
    in_library: bool = False
    source: str = "ijav"  # "ijav" (rich metadata) or "sukebei" (fallback, no cover/actress)
    stars: list[SearchResultStar] = []
    magnets: list[SearchResultMagnet] = []  # all candidates, best first (sync scoring)


class SearchResponse(BaseModel):
    query: str
    count: int
    items: list[SearchResultItem]
    actresses: list[SearchResultActress] = []  # name matches from the actress directory


def _norm_code(s: str) -> str:
    return re.sub(r"[^A-Za-z0-9]", "", s).upper()


# ── Remote cover proxy ───────────────────────────────────────────────
# ijavtorrent covers live on images.ijavtorrent.com (Bunny CDN behind
# Cloudflare). Hotlinking them in the browser is unreliable on mobile
# networks and gains nothing — no shared cache, no auth. Instead the first
# request downloads the image, caches it under images/search/, and every
# later request is a 307 to /images/search/<file> served statically by
# Caddy (same pattern as /api/cover and /api/social/x/media).
_COVER_DIR = Path(__file__).resolve().parents[2] / "images" / "search"
_COVER_HEADERS = {"Cache-Control": "public, max-age=2592000, immutable"}
_COVER_MAX_BYTES = 8 * 1024 * 1024
_COVER_PRUNE_AT = 2000
_ALLOWED_COVER_HOSTS = ("images.ijavtorrent.com", "ijavtorrent.com")
_COVER_EXTS = (".jpg", ".png", ".webp", ".gif")
_MIME_BY_EXT = {"image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp", "image/gif": ".gif"}


def _valid_cover_source(url: str) -> bool:
    """Only ijavtorrent's own image hosts — never an open proxy."""
    try:
        parts = urllib.parse.urlsplit(url)
    except ValueError:
        return False
    if parts.scheme not in ("http", "https"):
        return False
    host = (parts.hostname or "").lower()
    return any(host == h or host.endswith("." + h) for h in _ALLOWED_COVER_HOSTS)


def _cover_stem(url: str) -> str:
    return hashlib.sha1(url.encode("utf-8")).hexdigest()[:20]


def _cached_cover(url: str) -> str | None:
    """Cache filename for a remote URL, if it was downloaded before.

    The extension comes from the bytes (the CDN serves WebP under .jpg
    URLs), so every known extension is probed for the URL's stem.
    """
    stem = _cover_stem(url)
    for ext in _COVER_EXTS:
        name = f"{stem}{ext}"
        if (_COVER_DIR / name).exists():
            return name
    return None


def proxied_cover(url: str | None) -> str | None:
    """Browser-facing URL for a remote cover (None when not proxyable)."""
    if not url or not _valid_cover_source(url):
        return None
    return f"/api/search/cover?u={urllib.parse.quote(url, safe='')}"


def _image_mime(data: bytes) -> str:
    if data[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    if data[:4] == b"GIF8":
        return "image/gif"
    return ""


def _store_cover(name: str, data: bytes) -> bool:
    """Atomically write a cached cover, keeping the directory bounded."""
    tmp = _COVER_DIR / f".{name}.{os.getpid()}.{time.monotonic_ns()}.tmp"
    try:
        _COVER_DIR.mkdir(parents=True, exist_ok=True)
        tmp.write_bytes(data)
        os.replace(tmp, _COVER_DIR / name)
    except OSError as exc:
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass
        log.warning(f"cover cache write failed for {name}: {exc}")
        return False
    try:
        entries = [
            (e.stat().st_mtime, e.path)
            for e in os.scandir(_COVER_DIR)
            if e.is_file() and not e.name.startswith(".")
        ]
    except OSError:
        return True
    if len(entries) > _COVER_PRUNE_AT:
        entries.sort()
        for _, stale in entries[: len(entries) - _COVER_PRUNE_AT]:
            try:
                os.remove(stale)
            except OSError:
                pass
    return True


@router.get("/cover")
async def search_cover(u: str = Query(..., min_length=10, max_length=1000)) -> Response:
    """Local cache for remote cover images (see proxied_cover).

    Disk hit -> 307 to /images/search/<file> so Caddy serves the bytes.
    Miss -> download once, cache, serve. Failures stay a hard 404/502 so
    the UI can fall back to a code placeholder instead of a broken image.
    """
    url = u.strip()
    if not _valid_cover_source(url):
        raise HTTPException(status_code=400, detail="unsupported cover source")
    cached = _cached_cover(url)
    if cached:
        return RedirectResponse(
            url=f"/images/search/{cached}", status_code=307, headers=_COVER_HEADERS
        )

    from scrapers.v2.fetchers import HttpxFetcher

    try:
        async with HttpxFetcher(timeout=20.0) as fetcher:
            # The CDN enforces hotlink protection: a browser-like UA without
            # `Referer: https://ijavtorrent.com/` gets 403 (which is exactly
            # why hotlinked covers never rendered in the browser).
            data = await fetcher.fetch_bytes(url, headers={"Referer": IJAV_BASE_URL + "/"})
    except Exception as exc:
        log.warning(f"cover fetch failed for {url}: {exc}")
        raise HTTPException(status_code=502, detail="cover fetch failed") from None
    if not data or len(data) > _COVER_MAX_BYTES:
        raise HTTPException(status_code=502, detail="cover empty or too large")
    media_type = _image_mime(data)
    if not media_type:
        raise HTTPException(status_code=502, detail="not an image")

    name = f"{_cover_stem(url)}{_MIME_BY_EXT[media_type]}"
    if await asyncio.to_thread(_store_cover, name, data):
        return RedirectResponse(
            url=f"/images/search/{name}", status_code=307, headers=_COVER_HEADERS
        )
    return Response(content=data, media_type=media_type, headers=_COVER_HEADERS)


# Local actress directory index — offline fallback for the live
# /actresses?searchTerm= search (ijavtorrent down or empty). Crawled by
# scripts/build_actress_index.py; lazy-loaded, mtime-cached.
_ACTRESS_INDEX_PATH = Path(__file__).resolve().parents[2] / "data" / "actress_index.json"
_actress_index: tuple[float, list[dict]] | None = None


def _actress_matches(query: str, limit: int = 12) -> list[dict]:
    global _actress_index
    q = query.strip().lower()
    if len(q) < 2:
        return []
    try:
        mtime = _ACTRESS_INDEX_PATH.stat().st_mtime
    except OSError:
        return []
    if _actress_index is None or _actress_index[0] != mtime:
        try:
            data = json.loads(_ACTRESS_INDEX_PATH.read_text())
            _actress_index = (mtime, data.get("actresses", []))
        except Exception as exc:
            log.warning(f"actress index unreadable: {exc}")
            _actress_index = (mtime, [])
    entries = _actress_index[1]
    # Prefix matches rank above plain substring matches; ties break by
    # movie count so the famous names surface first.
    starts = sorted(
        (a for a in entries if a["name"].lower().startswith(q)),
        key=lambda a: -a.get("movies", 0),
    )
    contains = sorted(
        (a for a in entries if q in a["name"].lower() and not a["name"].lower().startswith(q)),
        key=lambda a: -a.get("movies", 0),
    )
    return (starts + contains)[:limit]


async def _ijav_items(fetcher, query: str) -> list[VideoItem]:
    # ?searchTerm= is ijavtorrent's search param since the 2026-09 redesign;
    # the old ?s= silently returns the homepage for every query.
    url = f"{IJAV_BASE_URL}/?searchTerm={urllib.parse.quote(query)}"
    html = await fetcher.fetch(url)
    return IJavTorrentExtractor().extract(html)


async def _ijav_actresses(fetcher, query: str) -> list[dict]:
    """Live actress directory search; empty list on any failure (the caller
    falls back to the offline-crawled local index)."""
    try:
        url = f"{IJAV_BASE_URL}/actresses?searchTerm={urllib.parse.quote(query)}"
        html = await fetcher.fetch(url)
        return parse_actress_directory(html)
    except Exception as exc:
        log.warning(f"actress directory search failed for {query!r}: {exc}")
        return []


def _best_actress_match(matches: list[dict], query: str) -> dict | None:
    """Directory results come in ijav's own order (fuzzy romaji); pick the
    one that actually looks like the query: name prefix first, then substring,
    then the busiest performer."""
    q = query.strip().lower()
    if not q or not matches:
        return None

    def rank(a: dict) -> tuple[int, int, int]:
        name = (a.get("name") or "").lower()
        return (
            0 if name.startswith(q) else 1,
            0 if q in name else 1,
            -int(a.get("movies") or 0),
        )

    return min(matches, key=rank)


async def _ijav_actress_titles(fetcher, actress_url: str) -> list[VideoItem]:
    """First page of an actress's own ijavtorrent listing (covers + links)."""
    html = await fetcher.fetch(actress_url)
    if not html.rstrip().endswith("</html>"):
        log.info(f"actress page truncated for {actress_url}")
    return IJavTorrentExtractor().extract(html)


async def _sukebei_exact(fetcher, query: str) -> list[VideoItem]:
    """sukebei RSS fallback for code lookups ijavtorrent can't serve."""
    url = SUKEBEI_RSS_URL.format(q=urllib.parse.quote(query))
    rss = await fetcher.fetch(url)
    if not rss.rstrip().endswith("</rss>"):
        log.warning(f"sukebei fallback: truncated rss for {query!r}")
        return []
    want = _norm_code(query)
    return [
        it for it in SukebeiRssExtractor().extract(rss)
        if it.magnets and _norm_code(it.code) == want
    ]


async def _fetch_items(query: str) -> tuple[list[tuple[VideoItem, str]], list[dict]]:
    """Fetch + extract + filter search results (60s TTL cache).

    Returns (work items, directory actresses); item source is "ijav" or
    "sukebei". Directory actresses come from ijavtorrent's live actress
    search — empty for code-like queries and on fetch failure.
    """
    key = query.strip().lower()
    hit = _items_cache.get(key)
    if hit and (time.time() - hit[0]) < _CACHE_TTL:
        return hit[1], hit[2]

    from scrapers.v2.fetchers import HttpxFetcher

    code_query = bool(_CODE_QUERY_RE.match(query.strip()))
    want = _norm_code(query)

    async with HttpxFetcher() as fetcher:
        # A code-like query can never be an actress name — skip the
        # directory round-trip.
        actresses = [] if code_query else await _ijav_actresses(fetcher, query.strip())
        items = await _ijav_items(fetcher, query.strip())

        kept: list[tuple[VideoItem, str]] = []
        if code_query:
            # Exact-match lookup: explicit user intent — skip the collection
            # filters (they exist to keep the catalog clean, not to hide a
            # work the user asked for by code); magnets still required.
            kept = [
                (it, "ijav") for it in items
                if it.magnets and _norm_code(it.code) == want
            ]
            if not kept:
                try:
                    kept = [(it, "sukebei") for it in await _sukebei_exact(fetcher, query.strip())]
                except Exception as exc:
                    log.warning(f"sukebei fallback failed for {query!r}: {exc}")
        else:
            config = _load_config()
            roster_names = [
                n for s in config.get("stars", []) for n in (s.get("name"), s.get("jp")) if n
            ]
            for it in items:
                # Same collection-stage rules as sync: drop VR / multi-star
                # and works with no magnet — they could never enter the library.
                if not it.magnets:
                    continue
                own_names = [s.name for s in it.star_links]
                if hidden_reason(it, own_names=own_names, roster_names=roster_names):
                    continue
                kept.append((it, "ijav"))

            # A name query the fuzzy full-text search answers with almost
            # nothing is best served by the matched actress's own page: her
            # works carry covers and actress links (so a follow button is
            # offered on every card). Only used when the directory matched,
            # so plain keyword searches keep ijav's own ordering.
            if len(kept) < 3 and actresses:
                best = _best_actress_match(actresses, query)
                try:
                    extra = await _ijav_actress_titles(
                        fetcher, (best or actresses[0])["url"]
                    )
                except Exception as exc:
                    log.info(f"actress-page fallback failed for {query!r}: {exc}")
                else:
                    have = {it.code for it, _ in kept}
                    for it in extra:
                        if it.code in have or not it.magnets:
                            continue
                        own_names = [s.name for s in it.star_links]
                        if hidden_reason(it, own_names=own_names, roster_names=roster_names):
                            continue
                        have.add(it.code)
                        kept.append((it, "ijav"))

    _items_cache[key] = (time.time(), kept, actresses)
    return kept, actresses


def _library_codes(codes: list[str]) -> set[str]:
    if not codes:
        return set()
    placeholders = ", ".join("%s" for _ in codes)
    conn = _db_conn()
    try:
        rows = conn.execute(
            f"SELECT code FROM titles WHERE code IN ({placeholders})", codes
        ).fetchall()
        return {r[0] for r in rows}
    finally:
        conn.close()


def _followed_index(config: dict) -> dict[str, str]:
    """actress id -> library code for everyone already followed.

    Compared by actress id, not by URL string: ijav links carry a trailing
    slash and the slug changes when a performer is renamed.
    """
    index: dict[str, str] = {}
    for star in config.get("stars", []):
        parsed = normalize_actress_url(star.get("star_page_url", ""))
        if parsed:
            index[parsed[2]] = star.get("code", "")
    return index


def _star_ref(name: str, url: str, followed: dict[str, str]) -> SearchResultStar:
    parsed = normalize_actress_url(url)
    code = followed.get(parsed[2], "") if parsed else ""
    return SearchResultStar(
        name=name,
        url=parsed[0] if parsed else url,
        code=code,
        followed=bool(code),
    )


@router.get("", response_model=SearchResponse)
async def search_titles(q: str = Query(..., min_length=2, max_length=100)) -> SearchResponse:
    """Search the catalog by code or keyword (ijavtorrent, sukebei fallback)."""
    query = q.strip()

    try:
        items, directory = await _fetch_items(query)
    except Exception as exc:
        log.warning(f"search fetch failed for {query!r}: {exc}")
        raise HTTPException(status_code=502, detail=f"检索失败: {exc}") from exc

    config = _load_config()
    followed = _followed_index(config)
    in_library = await db_read(_library_codes, [it.code for it, _ in items])

    results = []
    for it, source in items:
        # Same best-magnet selection as the sync pipeline (hhd800 bonus,
        # resolution tier, seeds, size) — not raw extractor order.
        scored = sorted(
            it.magnets, key=lambda m: TitleSyncSink._score_magnet(m), reverse=True
        )
        best = scored[0]
        results.append(
            SearchResultItem(
                code=it.code,
                title=it.title,
                release_date=it.release_date,
                views=it.views,
                likes=it.likes,
                cover_url=proxied_cover(it.cover_url),
                resolution=best.resolution,
                size=best.size,
                seeds=best.seed,
                in_library=it.code in in_library,
                source=source,
                stars=[
                    _star_ref(s.name, s.url, followed) for s in it.star_links
                ],
                magnets=[
                    SearchResultMagnet(
                        magnet=m.magnet,
                        resolution=m.resolution,
                        size=m.size,
                        seeds=m.seed,
                        is_hd=m.is_hhd800,
                    )
                    for m in scored
                ],
            )
        )

    log.info(f"search {query!r}: {len(results)} results")
    # Live directory search first; the offline-crawled local index is the
    # fallback when ijavtorrent returned nothing (down or no match).
    matches = (directory or _actress_matches(query))[:12]
    actresses = [
        SearchResultActress(
            **_star_ref(a["name"], a["url"], followed).model_dump(),
            image=proxied_cover(a.get("image", "")) or "",
        )
        for a in matches
    ]
    return SearchResponse(query=query, count=len(results), items=results, actresses=actresses)
