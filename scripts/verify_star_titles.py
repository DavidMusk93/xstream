"""scripts/verify_star_titles.py — Remove titles that belong to another actress

Root cause this repairs: sukebei RSS is a full-text name search, so a short
star name pulls in namesakes. ``Ichika`` matched ``Ichika Nagano`` /
``Ichika Hoshimiya`` / ``Ichika Sasa``; ``miru`` matched ``Miura Hamasaki``.
Those rows are stored under the wrong star and show up on her shelf.

The oracle is ijavtorrent's own work card: its ``/actress/`` links say who
performed. A row is deleted ONLY on positive evidence — a card that names a
different actress than the star (by page URL or name). A row with no card
(ijavtorrent lost most of its catalog in 2026-08), a fetch failure or an
ambiguous result is KEPT: a wrong deletion permanently loses a real work.
This matches ``scrapers/v2/verify.py``, which the sync pipeline now uses for
new rows.

Liked titles (user_liked=1) are never deleted — they are reported instead.

Usage:
    set -a; . /etc/xstream.env; set +a
    .venv/bin/python scripts/verify_star_titles.py                 # dry-run, full report
    .venv/bin/python scripts/verify_star_titles.py --apply         # delete
    .venv/bin/python scripts/verify_star_titles.py --star ICHIKA   # one star (code or name)
    .venv/bin/python scripts/verify_star_titles.py --all           # also re-check ijav-sourced rows

Deleted codes are sealed in title_blacklist (reason=other_star), so the next
sync does not re-add them; the 7-day retry window re-checks once and drops
them again if the source still attributes them elsewhere.

Stop the backend first with --apply: cached torrents of deleted rows become
orphans, and POST /api/cache/gc-orphans (or a restart) clears them.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scrapers.v2.fetchers import HttpxFetcher
from scrapers.v2.schemas import StarConfig
from scrapers.v2.verify import card_belongs_to, fetch_card_links

CONFIG_PATH = Path("config.json")
IMAGES_DIR = Path("images/titles")


def _load_stars(only: str | None):
    """Returns (star_id -> (StarConfig, db aliases), star_id -> [(title_id, code, liked)])."""
    from core.db import _conn

    with open(CONFIG_PATH, encoding="utf-8") as f:
        roster = json.load(f).get("stars", [])
    by_code: dict[str, dict] = {}
    by_name: dict[str, dict] = {}
    for s in roster:
        by_code[s.get("code", "").upper()] = s
        for n in (s.get("name"), s.get("jp")):
            if n:
                by_name[n.strip().lower()] = s

    conn = _conn()
    try:
        rows = conn.execute("SELECT id, name, jp_name, code FROM stars").fetchall()
        title_rows = conn.execute(
            "SELECT id, star_id, code, user_liked FROM titles ORDER BY star_id, code"
        ).fetchall()
    finally:
        conn.close()

    out: dict[int, StarConfig] = {}
    for star_id, name, jp_name, code in rows:
        cfg = by_code.get((code or "").upper())
        for alias in (name, jp_name):
            if cfg is None and alias:
                cfg = by_name.get(alias.strip().lower())
        if cfg is None:
            print(f"! star {name!r} (id={star_id}) has no config entry — skipped")
            continue
        if only and only.lower() not in {
            cfg.get("name", "").lower(), (cfg.get("code") or "").lower(), (name or "").lower(),
        }:
            continue
        out[star_id] = StarConfig(**cfg)

    grouped: dict[int, list[tuple[int, str, int]]] = {}
    for title_id, star_id, code, liked in title_rows:
        if star_id in out:
            grouped.setdefault(star_id, []).append((title_id, code, liked or 0))
    return out, grouped


async def _verify(star: StarConfig, rows: list[tuple[int, str, int]], concurrency: int):
    """Return (rejected, kept_unknown) — rejected only on positive evidence."""
    rejected: list[tuple[int, str, str, int]] = []
    unknown: list[tuple[int, str]] = []
    sem = asyncio.Semaphore(max(1, concurrency))

    async with HttpxFetcher() as fetcher:
        async def one(title_id: int, code: str, liked: int) -> None:
            async with sem:
                links = await fetch_card_links(fetcher, code)
            verdict = card_belongs_to(links or [], star)
            if verdict is False:
                names = ", ".join(l.name for l in (links or []))
                rejected.append((title_id, code, names, liked))
            elif verdict is None:
                unknown.append((title_id, code))

        await asyncio.gather(*(one(tid, code, liked) for tid, code, liked in rows))
    rejected.sort(key=lambda r: r[1])
    unknown.sort(key=lambda r: r[1])
    return rejected, unknown


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="actually delete (stop the backend first)")
    ap.add_argument("--star", help="only this star (config name, code or DB name)")
    ap.add_argument("--all", action="store_true",
                    help="check every row incl. ijav-sourced ones (default: all rows)")
    ap.add_argument("--concurrency", type=int, default=4)
    args = ap.parse_args()

    from core.db import _conn

    stars, grouped = _load_stars(args.star)
    if not stars:
        print("no stars matched")
        return

    total_rejected: list[tuple[int, str, str, int]] = []
    for star_id, star in sorted(stars.items(), key=lambda kv: kv[1].name):
        rows = grouped.get(star_id, [])
        if not rows:
            continue
        rejected, unknown = asyncio.run(_verify(star, rows, args.concurrency))
        total_rejected.extend(rejected)
        if rejected:
            print(f"\n== {star.name} ({star.code}): {len(rejected)}/{len(rows)} not hers")
            for _tid, code, names, liked in rejected:
                print(f"    - {code} → {names}{'  (LIKED, kept)' if liked else ''}")
        else:
            print(f"== {star.name}: {len(rows)} titles, all hers"
                  f" ({len(unknown)} without an ijavtorrent card, kept)")

    deletable = [r for r in total_rejected if not r[3]]
    print(f"\n{len(total_rejected)} misattributed, {len(deletable)} deletable,"
          f" {len(total_rejected) - len(deletable)} liked (kept)")

    if not args.apply:
        print("dry-run: pass --apply to delete")
        return
    if not deletable:
        return

    conn = _conn()
    try:
        with conn.transaction():
            conn.cursor().executemany(
                """
                INSERT INTO title_blacklist (star_id, code, reason)
                SELECT star_id, code, 'other_star' FROM titles WHERE id = %s
                ON CONFLICT (star_id, code) DO UPDATE SET
                    reason = EXCLUDED.reason,
                    skip_count = title_blacklist.skip_count + 1,
                    last_seen = now()
                """,
                [(r[0],) for r in deletable],
            )
            ids = [r[0] for r in deletable]
            placeholders = ", ".join(["%s"] * len(ids))
            conn.execute(f"DELETE FROM titles WHERE id IN ({placeholders})", ids)
    finally:
        conn.close()

    covers_removed = 0
    for _tid, code, _names, _liked in deletable:
        cover_dir = IMAGES_DIR / code.lower()
        if cover_dir.is_dir():
            shutil.rmtree(cover_dir, ignore_errors=True)
            covers_removed += 1
    print(f"deleted {len(deletable)} rows, removed {covers_removed} cover dirs,"
          " blacklisted as other_star")
    print("clear orphaned caches with POST /api/cache/gc-orphans")


if __name__ == "__main__":
    main()
