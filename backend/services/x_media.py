"""backend/services/x_media.py — Local cache for X (pbs.twimg.com) images

Injected X posts reference remote pbs.twimg.com images. Hotlinking them gave
users a poor loading experience (slow cross-border fetches, top-down JPEG
paint), so media is cached on this machine and served like a CDN:

  inject (POST /api/social/x)
    -> warm() prefetches avatar + post media into images/x/{key}.{ext}
  /api/stars payload rewrite (stars.py)
    -> media/avatar URLs become /api/social/x/media/{key}.{ext}?u=<original>
  GET /api/social/x/media/{filename}
    -> disk hit:  307 -> /images/x/{filename}  (Caddy static, immutable)
    -> disk miss: download u (validated), store, serve bytes

The `u` parameter keeps the proxy self-contained — no hash->URL mapping table
— and lets the client fall back to the original URL on error.

Security: only https://pbs.twimg.com is ever fetched, so this endpoint can
never be used as an open proxy (same guarantee x_inject enforces on inject).
"""

from __future__ import annotations

import asyncio
import hashlib
import os
import re
from pathlib import Path
from urllib.parse import parse_qs, quote, urlsplit

import httpx

from core.logger import get_logger

log = get_logger("x-media")

SCRIPT_DIR = Path(__file__).resolve().parent.parent.parent
MEDIA_DIR = SCRIPT_DIR / "images" / "x"

ALLOWED_HOST = "pbs.twimg.com"
MAX_BYTES = 12 * 1024 * 1024
TIMEOUT = 10.0
_EXT_WHITELIST = {"jpg", "jpeg", "png", "webp", "gif"}
_FILENAME_RE = re.compile(r"^[a-f0-9]{24}\.(?:jpg|png|webp|gif)$")

_WARM_LIMIT = 4


def cache_key(url: str) -> str:
    """Stable content-independent key for a source URL."""
    return hashlib.blake2b(url.encode("utf-8"), digest_size=12).hexdigest()


def _ext_of(url: str) -> str:
    parts = urlsplit(url)
    fmt = (parse_qs(parts.query).get("format") or [""])[0].lower()
    if fmt in _EXT_WHITELIST:
        return "jpg" if fmt == "jpeg" else fmt
    suffix = parts.path.rsplit(".", 1)[-1].lower() if "." in parts.path.rsplit("/", 1)[-1] else ""
    if suffix in _EXT_WHITELIST:
        return "jpg" if suffix == "jpeg" else suffix
    return "jpg"


def filename_for(url: str) -> str:
    return f"{cache_key(url)}.{_ext_of(url)}"


def validate_source(url: str) -> bool:
    """Only https://pbs.twimg.com may be fetched — never an open proxy."""
    try:
        parts = urlsplit(url)
    except ValueError:
        return False
    return parts.scheme == "https" and parts.hostname == ALLOWED_HOST


def proxy_url(url: str) -> str:
    """Rewrite a twimg URL to the local proxy; pass anything else through."""
    if not validate_source(url):
        return url
    return f"/api/social/x/media/{filename_for(url)}?u={quote(url, safe='')}"


def valid_filename(filename: str) -> bool:
    return bool(_FILENAME_RE.match(filename))


def cached_path(filename: str) -> Path | None:
    """Disk path for a validated cache filename, or None when not cached."""
    if not valid_filename(filename):
        return None
    path = MEDIA_DIR / filename
    return path if path.is_file() and path.stat().st_size > 0 else None


async def fetch_to_cache(url: str) -> Path | None:
    """Download a validated twimg URL into images/x/; returns the file path."""
    if not validate_source(url):
        log.warning(f"x media rejected (not twimg): {url[:120]}")
        return None
    filename = filename_for(url)
    existing = cached_path(filename)
    if existing:
        return existing
    try:
        MEDIA_DIR.mkdir(parents=True, exist_ok=True)
        async with httpx.AsyncClient(timeout=TIMEOUT, follow_redirects=True) as client:
            async with client.stream("GET", url) as resp:
                if resp.status_code != 200:
                    log.warning(f"x media fetch {resp.status_code}: {url[:120]}")
                    return None
                content_type = resp.headers.get("content-type", "")
                if not content_type.startswith("image/"):
                    log.warning(f"x media rejected (content-type {content_type}): {url[:120]}")
                    return None
                tmp = MEDIA_DIR / f".{filename}.tmp"
                size = 0
                with open(tmp, "wb") as f:
                    async for chunk in resp.aiter_bytes(64 * 1024):
                        size += len(chunk)
                        if size > MAX_BYTES:
                            f.close()
                            tmp.unlink(missing_ok=True)
                            log.warning(f"x media rejected (too large): {url[:120]}")
                            return None
                        f.write(chunk)
        os.replace(tmp, MEDIA_DIR / filename)
        return MEDIA_DIR / filename
    except Exception as exc:
        log.warning(f"x media fetch failed: {url[:120]}: {exc}")
        return None


async def warm(urls: list[str | None]) -> None:
    """Best-effort prefetch of injected media so the first view hits disk."""
    todo = [u for u in dict.fromkeys(urls) if u and validate_source(u)]
    if not todo:
        return
    sem = asyncio.Semaphore(_WARM_LIMIT)

    async def one(url: str) -> None:
        async with sem:
            await fetch_to_cache(url)

    results = await asyncio.gather(*(one(u) for u in todo))
    ok = sum(1 for r in results if r)
    log.info(f"x media warm: {ok}/{len(todo)} cached")
