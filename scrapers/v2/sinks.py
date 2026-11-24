"""scrapers/v2/sinks.py — Unified write layer (wide-table simplified)

Write extraction results directly to the titles wide table via UPSERT;
all works of one star need only one SQL execution, completely eliminating serial queue bottleneck.
Cover blobs go to the separate title_covers table (1:1 with titles).
"""

from __future__ import annotations

import json
import re
from typing import Protocol

from psycopg.types.json import Jsonb
import xstream_core

from core import db
from core.db.write_queue import db_write
from core.logger import get_logger
from scrapers.v2.schemas import VideoItem, MagnetCandidate

log = get_logger("title-sync-sink")

# Covers taller than wide are never legit full covers — they are vertical
# front-cover thumbnails (e.g. ijavtorrent's 300x426 / 564x800) that break
# the aspect-ratio placeholders in list rendering. Normal covers are 0.6-0.8.
COVER_MAX_HW_RATIO = 1.0

# PostgreSQL two-key advisory lock namespace for per-star title upserts.
_SYNC_STAR_LOCK_NS = 728_301


class Sink(Protocol):
    """Sink protocol"""

    async def write(self, item):
        ...


class TitleSyncSink:
    """Sync work data to PostgreSQL (wide-table UPSERT mode)

    Batch UPSERT per star, no need to preload existing_codes,
    no need to judge new/old, no serial write queue round-trips.
    """

    def __init__(self, star_id: int, star_code: str, star_name: str):
        self.star_id = star_id
        self.star_code = star_code
        self.star_name = star_name

    async def write(self, item: VideoItem, cover_b64: str | None = None) -> None:
        """Write single title (backward-compatible interface, internally still uses batch)."""
        await self.write_batch([item], {it.code for it in [item]}, {item.code: cover_b64 or ""})

    async def write_batch(
        self, items: list[VideoItem], new_codes: set[str], cover_map: dict[str, str]
    ) -> dict[str, int]:
        """Batch UPSERT all titles for this star in one SQL.

        Build multi-row VALUES + ON CONFLICT DO UPDATE,
        leveraging PostgreSQL native UPSERT capability, no manual insert/update judgment needed.
        """
        import time as _time

        if not items:
            return {"new": 0, "updated": 0, "skipped_no_magnet": 0,
                    "skipped_bad_cover": 0, "skipped_no_cover": 0}

        t0 = _time.perf_counter()
        values = []
        skipped_no_magnet = 0
        skipped_bad_cover = 0
        skipped_no_cover = 0
        skips: dict[str, str] = {}  # code → first skip reason (for title_blacklist)
        for item in items:
            # Never record titles without a usable magnet: they are unplayable
            # and only clutter the catalog. Candidates whose btih hash cannot
            # be extracted count as unusable. A source listing the code with
            # valid magnets later will insert it then.
            scored = sorted(
                (m for m in item.magnets if _extract_hash(m.magnet)),
                key=lambda m: TitleSyncSink._score_magnet(m),
                reverse=True,
            )
            if not scored:
                skipped_no_magnet += 1
                skips.setdefault(item.code, "no_magnet")
                continue
            primary = scored[0]
            primary_hash = _extract_hash(primary.magnet)

            all_magnets = [
                {
                    "hash": _extract_hash(m.magnet) or "",
                    "magnet": m.magnet,
                    "resolution": m.resolution,
                    "size": m.size,
                    "seed": m.seed,
                    "leech": m.leech,
                }
                for m in scored
            ]

            cover_b64 = cover_map.get(item.code) or ""
            cover_dims = db._cover_dims_from_b64(cover_b64)
            if cover_dims and cover_dims[1] / cover_dims[0] > COVER_MAX_HW_RATIO:
                # Taller-than-wide covers are vertical front-cover thumbnails,
                # not usable covers — drop the blob and treat as coverless.
                skipped_bad_cover += 1
                skips.setdefault(item.code, "bad_cover")
                cover_b64 = ""
                cover_dims = None
            if not cover_b64 and item.code in new_codes:
                # New titles without a cover never enter the DB; the
                # blacklist record stops future syncs from re-downloading it.
                skipped_no_cover += 1
                skips.setdefault(item.code, "no_cover")
                continue
            values.append({
                "star_id": self.star_id,
                "star_code": self.star_code,
                "star_name": self.star_name,
                "code": item.code,
                "title": item.title,
                "release_date": item.release_date,
                "release_date_sort": db._date_to_sort(item.release_date),
                "views": item.views,
                "likes": item.likes,
                "resolution": primary.resolution,
                "cover_url": item.cover_url,
                "cover_b64": cover_b64,
                "cover_w": cover_dims[0] if cover_dims else None,
                "cover_h": cover_dims[1] if cover_dims else None,
                "magnet": primary.magnet,
                "magnet_hash": primary_hash,
                "all_magnets": Jsonb(all_magnets) if all_magnets else None,
                "_candidates": scored,
            })

        def _upsert(conn=None) -> dict[str, int]:
            managed = conn if conn is not None else db._conn()
            should_close = conn is None
            try:
                # Pool connections are autocommit: wrap the multi-statement
                # upsert in an explicit transaction so rows + covers land atomically.
                with managed.transaction():
                    # Serialize concurrent upserts for the same star inside
                    # PostgreSQL (e.g. sync_star vs scheduled full sync) while
                    # allowing different stars to write in parallel.
                    managed.execute(
                        "SELECT pg_advisory_xact_lock(%s, %s)",
                        (_SYNC_STAR_LOCK_NS, self.star_id),
                    )
                    # Preserve existing live magnet candidates when upserting so
                    # an ijav-only phase-A pass (or stale concurrent write) can
                    # never clobber an HD magnet already written by RSS/code
                    # fallback. Dead rows are replaced cleanly.
                    existing_rows = managed.execute(
                        "SELECT code, all_magnets, magnet_status FROM titles"
                        " WHERE star_id = %s AND code = ANY(%s)",
                        (self.star_id, [v["code"] for v in values]),
                    ).fetchall()
                    existing_by_code = {
                        code: (mags, status) for code, mags, status in existing_rows
                    }
                    for v in values:
                        ex = existing_by_code.get(v["code"])
                        if not ex or ex[1] == "dead" or not ex[0]:
                            continue
                        ex_mags = json.loads(ex[0]) if isinstance(ex[0], str) else ex[0]
                        if not isinstance(ex_mags, list):
                            continue
                        incoming: list[MagnetCandidate] = list(v["_candidates"])
                        seen_hashes = {
                            _extract_hash(m.magnet) for m in incoming
                        }
                        added = False
                        for entry in ex_mags:
                            if not isinstance(entry, dict):
                                continue
                            mag_url = entry.get("magnet") or ""
                            h = _extract_hash(mag_url)
                            if not h or h in seen_hashes:
                                continue
                            seen_hashes.add(h)
                            low_url = mag_url.lower()
                            incoming.append(MagnetCandidate(
                                magnet=mag_url,
                                resolution=str(entry.get("resolution") or ""),
                                size=str(entry.get("size") or ""),
                                seed=int(entry.get("seed") or 0),
                                leech=int(entry.get("leech") or 0),
                                is_hhd800=("hhd800" in low_url or "%2b%2b%2b" in low_url or "+++" in low_url),
                            ))
                            added = True
                        if added:
                            merged_scored = sorted(
                                incoming,
                                key=lambda m: TitleSyncSink._score_magnet(m),
                                reverse=True,
                            )
                            best = merged_scored[0]
                            v["resolution"] = best.resolution
                            v["magnet"] = best.magnet
                            v["magnet_hash"] = _extract_hash(best.magnet)
                            v["all_magnets"] = Jsonb([
                                {
                                    "hash": _extract_hash(m.magnet) or "",
                                    "magnet": m.magnet,
                                    "resolution": m.resolution,
                                    "size": m.size,
                                    "seed": m.seed,
                                    "leech": m.leech,
                                }
                                for m in merged_scored
                            ])

                    # INSERT ... ON CONFLICT DO UPDATE, RETURNING id+code for the
                    # cover upsert below (works for both inserted and updated rows).
                    placeholders = ", ".join([
                        "(" + ", ".join(["%s"] * 16) + ")"
                        for _ in values
                    ])
                    flat = []
                    for v in values:
                        flat.extend([
                            v["star_id"], v["star_code"], v["star_name"],
                            v["code"], v["title"], v["release_date"], v["release_date_sort"],
                            v["views"], v["likes"], v["resolution"],
                            v["cover_url"], v["cover_w"], v["cover_h"],
                            v["magnet"], v["magnet_hash"], v["all_magnets"],
                        ])

                    # ON CONFLICT only updates metadata. Covers are deliberately
                    # kept out of this statement: they live in the title_covers
                    # table, and an empty fresh cover must never wipe an existing
                    # one. Fresh covers are applied separately below, only for
                    # rows that actually have one.
                    rows = managed.execute(
                        f"""
                        INSERT INTO titles (
                            star_id, star_code, star_name, code, title,
                            release_date, release_date_sort, views, likes,
                            resolution, cover_url, cover_w, cover_h,
                            magnet, magnet_hash, all_magnets
                        )
                        VALUES {placeholders}
                        ON CONFLICT (star_id, code) DO UPDATE SET
                            star_code = EXCLUDED.star_code,
                            star_name = EXCLUDED.star_name,
                            title = EXCLUDED.title,
                            release_date = EXCLUDED.release_date,
                            release_date_sort = EXCLUDED.release_date_sort,
                            views = EXCLUDED.views,
                            likes = EXCLUDED.likes,
                            resolution = EXCLUDED.resolution,
                            cover_url = EXCLUDED.cover_url,
                            magnet = EXCLUDED.magnet,
                            magnet_hash = EXCLUDED.magnet_hash,
                            all_magnets = EXCLUDED.all_magnets,
                            updated_at = now()
                        -- Backfill candidates the source cannot fix (~200 per
                        -- run) arrive unchanged every sync: skip the no-op
                        -- rewrite. Unchanged rows are not RETURNed.
                        WHERE (titles.star_code, titles.star_name, titles.title,
                               titles.release_date, titles.release_date_sort,
                               titles.views, titles.likes, titles.resolution,
                               titles.cover_url, titles.magnet, titles.magnet_hash,
                               titles.all_magnets)
                        IS DISTINCT FROM
                              (EXCLUDED.star_code, EXCLUDED.star_name, EXCLUDED.title,
                               EXCLUDED.release_date, EXCLUDED.release_date_sort,
                               EXCLUDED.views, EXCLUDED.likes, EXCLUDED.resolution,
                               EXCLUDED.cover_url, EXCLUDED.magnet, EXCLUDED.magnet_hash,
                               EXCLUDED.all_magnets)
                        RETURNING id, code
                        """,
                        flat,
                    ).fetchall()
                    id_by_code = {row[1]: row[0] for row in rows}
                    changed_codes = set(id_by_code)

                    new_covers = [v for v in values if v["cover_b64"]]
                    unreturned = [v["code"] for v in new_covers if v["code"] not in id_by_code]
                    if unreturned:
                        id_by_code.update(
                            (code, title_id) for title_id, code in managed.execute(
                                "SELECT id, code FROM titles WHERE star_id = %s AND code = ANY(%s)",
                                (self.star_id, unreturned),
                            ).fetchall()
                        )
                    if new_covers:
                        with managed.cursor() as cur:
                            cur.executemany(
                                """
                                INSERT INTO title_covers (title_id, cover_data)
                                VALUES (%s, %s)
                                ON CONFLICT (title_id) DO UPDATE SET
                                    cover_data = EXCLUDED.cover_data,
                                    updated_at = now()
                                """,
                                [(id_by_code[v["code"]], db.cover_bytes(v["cover_b64"]))
                                 for v in new_covers],
                            )
                            cur.executemany(
                                "UPDATE titles SET cover_w = %s, cover_h = %s,"
                                " updated_at = now() WHERE id = %s",
                                [(v["cover_w"], v["cover_h"], id_by_code[v["code"]]) for v in new_covers],
                            )

                # Export fresh covers to disk (full + thumb) so the frontend
                # gets direct static URLs right away instead of going through
                # the /api/cover DB fallback until the next manual export.
                for v in values:
                    if v["cover_b64"]:
                        db._write_cover_to_disk(v["code"], v["cover_b64"])

                # Persist skips so future syncs stop re-downloading covers
                # for titles that can never be accepted (see title_blacklist).
                # Codes written this round (retry-window passes that finally
                # succeeded) leave the blacklist again.
                db.clear_blacklist_entries(managed, self.star_id, [v["code"] for v in values])
                db.record_blacklist_skips(managed, self.star_id, list(skips.items()))

                # Count insert vs update this round; skipped new codes (no
                # usable cover) must not inflate the new count, and existing
                # rows count as updated only if metadata or cover changed.
                new_count = sum(1 for v in values if v["code"] in new_codes)
                updated_count = sum(
                    1 for v in values
                    if v["code"] not in new_codes
                    and (v["code"] in changed_codes or v["cover_b64"])
                )

                return {
                    "new": max(0, new_count),
                    "updated": max(0, updated_count),
                    "skipped_no_magnet": skipped_no_magnet,
                    "skipped_bad_cover": skipped_bad_cover,
                    "skipped_no_cover": skipped_no_cover,
                }
            finally:
                if should_close:
                    managed.close()

        if not values:
            log.info(
                f"write_batch: {self.star_name}: all {len(items)} items skipped"
                f" (no_magnet={skipped_no_magnet}, no_cover={skipped_no_cover})"
            )
            if skips:
                def _record_only(conn=None) -> None:
                    managed = conn if conn is not None else db._conn()
                    should_close = conn is None
                    try:
                        db.record_blacklist_skips(managed, self.star_id, list(skips.items()))
                    finally:
                        if should_close:
                            managed.close()

                await db_write(_record_only)
            return {"new": 0, "updated": 0, "skipped_no_magnet": skipped_no_magnet,
                    "skipped_bad_cover": skipped_bad_cover, "skipped_no_cover": skipped_no_cover}

        result = await db_write(_upsert)
        elapsed = (_time.perf_counter() - t0) * 1000
        skipped = (
            f" (skipped: no_magnet={skipped_no_magnet},"
            f" bad_cover={skipped_bad_cover}, no_cover={skipped_no_cover})"
            if skipped_no_magnet or skipped_bad_cover or skipped_no_cover else ""
        )
        log.info(f"write_batch: {self.star_name}: {len(values)} items in {elapsed:.1f}ms{skipped}")
        return result

    @staticmethod
    def _best_resolution(item: VideoItem) -> str:
        """Pick the best resolution string from candidates (for titles table)"""
        if not item.magnets:
            return ""
        best = max(item.magnets, key=lambda m: TitleSyncSink._score_magnet(m))
        return best.resolution

    @staticmethod
    def _score_magnet(m: MagnetCandidate) -> float:
        """MagnetCandidate scoring (delegated to Rust xstream_core)."""
        return xstream_core.py_score_magnet(
            m.resolution or "",
            m.size or "",
            int(m.seed or 0),
            bool(m.is_hhd800),
        )


class StdoutSink:
    """Debug use: direct print"""

    async def write(self, item):
        print(item)


def _extract_hash(magnet: str | None) -> str | None:
    m = re.search(r"xt=urn:btih:([a-f0-9]{40})", magnet or "", re.I)
    return m.group(1).lower() if m else None
