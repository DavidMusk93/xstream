"""scrapers/v2/verify.py — Star attribution check (作品归属校验)

A star's shelf must contain only her own works. Two things break that:

1. **sukebei RSS name matching** is a full-text search. Short names collide
   with other actresses: a query for ``Ichika`` returns ``Ichika Nagano`` /
   ``Ichika Hoshimiya`` / ``Ichika Sasa`` works, and they are stored under
   the wrong star.
2. **ijavtorrent actress pages** are authoritative, so a card that lists a
   different actress there means the source itself is confused.

The check here is deliberately positive-evidence-only: a work is rejected
**only** when a source explicitly names a different actress. "No card
found" (ijavtorrent lost most of its catalog in 2026-08) or a fetch failure
never drops a work — a false positive permanently loses a legit title.

Used by the sync pipeline (new RSS-only codes) and by
``scripts/verify_star_titles.py`` (existing rows).
"""

from __future__ import annotations

import asyncio
from typing import Iterable

from core.logger import get_logger
from scrapers.v2.extractors import IJAV_CODE_SEARCH_URL, IJavTorrentExtractor
from scrapers.v2.schemas import StarConfig, StarLink, VideoItem

log = get_logger("star-verify")


def _norm_url(url: str | None) -> str:
    return (url or "").strip().rstrip("/").lower()


def _norm_name(name: str | None) -> str:
    return " ".join((name or "").strip().lower().split())


def star_aliases(star: StarConfig) -> set[str]:
    """Names that identify the synced star (config name + romaji/jp alias)."""
    return {n for n in (_norm_name(star.name), _norm_name(star.jp)) if n}


def card_belongs_to(links: Iterable[StarLink], star: StarConfig) -> bool | None:
    """Whether an ijavtorrent card's actress links name the synced star.

    Returns None when the card names no actress at all (nothing to judge by),
    True when any link is her page URL (preferred, exact) or her name.
    """
    links = list(links or [])
    if not links:
        return None
    page = _norm_url(star.star_page_url)
    names = star_aliases(star)
    for link in links:
        if page and _norm_url(link.url) == page:
            return True
        if _norm_name(link.name) in names:
            return True
    return False


def item_belongs_to(item: VideoItem, star: StarConfig) -> bool | None:
    """Attribution verdict for an item that already carries actress links."""
    return card_belongs_to(item.star_links, star)


async def fetch_card_links(
    fetcher, code: str, attempts: int = 2, delay: float = 1.5
) -> list[StarLink] | None:
    """Actress links ijavtorrent shows for an exact code, or None when unknown.

    None (no card / fetch failed) is never evidence against a work — the
    caller must treat it as "keep".
    """
    want = code.strip().upper()
    for attempt in range(1, attempts + 1):
        try:
            html = await fetcher.fetch(IJAV_CODE_SEARCH_URL.format(q=want))
        except Exception as exc:
            log.info(f"attribution lookup failed for {want} (attempt {attempt}): {exc}")
        else:
            if html.rstrip().endswith("</html>"):
                for item in IJavTorrentExtractor().extract(html):
                    if item.code == want:
                        return item.star_links
                return None
            log.info(f"attribution lookup truncated for {want} (attempt {attempt})")
        if attempt < attempts:
            await asyncio.sleep(delay)
    return None


async def reject_misattributed(
    fetcher,
    star: StarConfig,
    items: list[VideoItem],
    *,
    concurrency: int = 4,
) -> tuple[list[VideoItem], list[tuple[str, str]]]:
    """Split items into (kept, [(code, reason)]) by actress attribution.

    Items that already list actresses are judged locally (no request); only
    link-less items (RSS-only, amateur codes) need the per-code ijavtorrent
    lookup. Rejections are positive evidence only (see the module docstring).
    """
    if not items:
        return [], []

    kept: list[VideoItem] = []
    rejected: list[tuple[str, str]] = []
    rejected_codes: set[str] = set()
    to_lookup: list[VideoItem] = []
    for item in items:
        verdict = item_belongs_to(item, star)
        if verdict is False:
            rejected.append((item.code, "other_star"))
            rejected_codes.add(item.code)
        elif verdict is None:
            to_lookup.append(item)
        else:
            kept.append(item)

    if to_lookup:
        sem = asyncio.Semaphore(max(1, concurrency))

        async def one(item: VideoItem) -> None:
            async with sem:
                links = await fetch_card_links(fetcher, item.code)
            verdict = card_belongs_to(links or [], star)
            if verdict is False:
                names = ", ".join(l.name for l in (links or []))
                log.info(f"{star.name}: dropping {item.code} — belongs to {names}")
                rejected.append((item.code, "other_star"))
            else:
                kept.append(item)

        await asyncio.gather(*(one(item) for item in to_lookup))
        rejected_codes |= {code for code, _ in rejected}

    # Input order is preserved (newest-first from the source) — MAX_NEW_TITLES
    # truncation downstream must keep the newest works.
    kept = [it for it in items if it.code not in rejected_codes]
    return kept, rejected
