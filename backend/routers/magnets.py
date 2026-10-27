"""backend/routers/magnets.py — Magnet liveness check router

Validates that a title's primary magnet actually has a live swarm (metadata
fetchable via DHT/trackers). Dead primaries are automatically swapped to the
next live candidate from all_magnets (already sorted best-first by the sync
sink); titles with no live candidate are marked magnet_status='dead' so the
frontend can grey them out.

Triggered manually (POST /api/magnets/check), by scripts/check_magnets.py for
the full historical sweep, and automatically after every successful title
sync (scope=changed). Progress is pushed over SSE.
"""

from __future__ import annotations

import asyncio
import json
import os
import time
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from backend.routers.auth import require_auth
from backend.services.magnet_checker import MagnetChecker, extract_hash, has_cached_torrent
from core import db, get_logger
from core.db.write_queue import db_read, db_write
from core.events import publish_event

router = APIRouter(prefix="/api/magnets", tags=["magnets"], dependencies=[Depends(require_auth)])
log = get_logger("magnet-check")

SCRIPT_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
CACHE_DIR = os.path.join(SCRIPT_DIR, "cache", "torrent")
CHECK_WORK_DIR = os.path.join(SCRIPT_DIR, "cache", "magnet-check")
IMAGES_DIR = os.path.join(SCRIPT_DIR, "images", "titles")
# Unplayable titles are hidden by /api/stars immediately; the row (cover,
# candidates) is retired this long after it was first found unplayable.
TTL_DAYS = db.DEAD_PURGE_TTL_DAYS
OK_RECHECK_DAYS = db.OK_RECHECK_DAYS

_checker: MagnetChecker | None = None
_check_lock = asyncio.Lock()
_check_state: dict[str, Any] = {
    "running": False,
    "scope": None,
    "total": 0,
    "done": 0,
    "alive": 0,
    "dead": 0,
    "swapped": 0,
    "started_at": None,
}
_check_task: asyncio.Task[Any] | None = None
_last_progress_push = 0.0


def get_checker() -> MagnetChecker:
    """Process-level checker singleton (own libtorrent session, lazy)."""
    global _checker
    if _checker is None:
        _checker = MagnetChecker(CHECK_WORK_DIR)
    return _checker


_engine: Any = None


def set_engine(engine: Any) -> None:
    """Register the streaming engine (lifespan) for the post-check TTL sweep."""
    global _engine
    _engine = engine


def shutdown_checker() -> None:
    global _checker
    if _checker is not None:
        _checker.shutdown()
        _checker = None


class CheckRequest(BaseModel):
    scope: str = Field(default="changed", pattern="^(all|dead|unchecked|changed)$")


def _ok_check_is_stale(item: dict[str, Any]) -> bool:
    """True when a prior ok verdict is old enough that the swarm may have died."""
    if item.get("magnet_status") != "ok":
        return False
    checked = item.get("magnet_checked_at")
    if checked is None:
        return False
    if checked.tzinfo is None:
        checked = checked.replace(tzinfo=timezone.utc)
    return checked < datetime.now(timezone.utc) - timedelta(days=OK_RECHECK_DAYS)


def _candidates(item: dict[str, Any], skip_hash: str | None) -> list[dict[str, Any]]:
    """Parse all_magnets, dropping the dead primary and malformed rows.

    JSONB columns come back from psycopg3 already parsed; a raw string is
    still accepted for robustness.
    """
    raw = item.get("all_magnets")
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except (TypeError, ValueError):
            return []
    mags = raw if isinstance(raw, list) else []
    return [m for m in mags if isinstance(m, dict) and m.get("magnet") and m.get("hash") != skip_hash]


def _process_title(item: dict[str, Any]) -> dict[str, Any]:
    """Per-title check: primary first, live-candidate fallback when dead.

    Runs on a MagnetChecker worker thread.
    """
    checker = get_checker()
    primary_hash = item.get("magnet_hash") or extract_hash(item["magnet"])
    res = checker.check_one(item["magnet"])
    if res["alive"]:
        return {"alive": True, "status": "ok", "hash": primary_hash, "peers": res["peers"]}

    # Primary is dead — walk the best-first candidate list for a live one.
    for cand in _candidates(item, primary_hash):
        res = checker.check_one(cand["magnet"])
        if res["alive"]:
            log.info(f"swap {item['code']}: dead primary -> {cand['hash'][:12]}...")
            return {
                "alive": True,
                "status": "swapped",
                "hash": cand["hash"],
                "magnet": cand["magnet"],
                "peers": res["peers"],
            }
    return {"alive": False, "status": "dead", "hash": primary_hash}


async def _persist_outcome(item: dict[str, Any], outcome: dict[str, Any]) -> None:
    """Persist one title's check outcome via the serial write queue."""
    from backend.routers.stars import invalidate_stars_cache

    try:
        if outcome["status"] == "ok":
            await db_write(db.update_magnet_check_ok, item["id"], outcome.get("hash"))
            # ok-only refresh does not change /api/stars (same magnet, still playable).
            # Bulk magnet checks used to invalidate ~2k times and rebuild the 2.8MB
            # payload each time — access logs showed /api/stars avg ~618ms p95 ~2s.
        elif outcome["status"] == "swapped":
            await db_write(db.swap_primary_magnet, item["id"], outcome["magnet"], outcome["hash"])
            invalidate_stars_cache()
        else:
            await db_write(db.update_magnet_check_dead, item["id"], outcome.get("hash"))
            invalidate_stars_cache()
    except Exception:
        log.exception(f"failed to persist magnet check for {item.get('code')}")

    global _last_progress_push
    async with _check_lock:
        _check_state["done"] += 1
        if outcome["status"] == "ok":
            _check_state["alive"] += 1
        elif outcome["status"] == "swapped":
            _check_state["swapped"] += 1
            _check_state["alive"] += 1
        else:
            _check_state["dead"] += 1
        done = _check_state["done"]

    now = time.time()
    if done % 20 == 0 or now - _last_progress_push >= 5:
        _last_progress_push = now
        await publish_event("magnets.check_progress", {
            "scope": _check_state["scope"],
            "total": _check_state["total"],
            "done": done,
            "alive": _check_state["alive"],
            "dead": _check_state["dead"],
            "swapped": _check_state["swapped"],
        })


async def _run_check_bg(scope: str) -> None:
    global _check_state, _last_progress_push
    started_at = _check_state["started_at"]
    pending: list[asyncio.Future] = []
    summary: dict[str, Any] = {}
    try:
        titles = await db_read(db.load_titles_for_magnet_check, scope)
        # Disk-is-truth shortcut: a cached .torrent proves the swarm works.
        network_items: list[dict[str, Any]] = []
        cached_ok = 0
        for t in titles:
            h = t.get("magnet_hash") or extract_hash(t["magnet"])
            # Cached .torrent skips network only for fresh ok rows; stale ok must
            # re-probe metadata because the swarm may have died since Sept sweep.
            if (
                h
                and has_cached_torrent(CACHE_DIR, h)
                and not _ok_check_is_stale(t)
            ):
                pending.append(asyncio.ensure_future(
                    _persist_outcome(t, {"alive": True, "status": "ok", "hash": h})
                ))
                cached_ok += 1
            else:
                network_items.append(t)

        async with _check_lock:
            _check_state["total"] = len(titles)
        log.info(f"magnet check [{scope}]: {len(titles)} titles ({cached_ok} cached, {len(network_items)} network)")

        loop = asyncio.get_running_loop()

        def on_result(item: dict[str, Any], outcome: dict[str, Any]) -> None:
            future = asyncio.run_coroutine_threadsafe(_persist_outcome(item, outcome), loop)
            pending.append(asyncio.wrap_future(future, loop=loop))

        if network_items:
            await asyncio.to_thread(
                get_checker().check_batch, network_items, _process_title, on_result
            )

        if pending:
            await asyncio.gather(*pending, return_exceptions=True)

        async with _check_lock:
            summary = {k: _check_state[k] for k in ("scope", "total", "done", "alive", "dead", "swapped")}
        summary["elapsed"] = round(time.time() - started_at, 1) if started_at else 0
        log.info(f"magnet check finished: {summary}")
        await publish_event("magnets.check_completed", summary)
    except Exception as e:
        log.error(f"magnet check exception: {e}", exc_info=True)
        await publish_event("magnets.check_error", {"scope": scope, "error": str(e)[:200]})
    finally:
        async with _check_lock:
            _check_state["running"] = False

    # TTL sweep: unplayable titles have been hidden from /api/stars since the
    # moment they went dead; only now, TTL_DAYS after that, is the row retired
    # (blacklisted + deleted) so a temporarily starved swarm could still come
    # back through the regular re-check. Runs outside the check lock: the
    # state is already "not running", and _purge_unplayable never takes it.
    if summary:
        try:
            purged = await _purge_unplayable(_engine, ttl_days=TTL_DAYS)
            if purged["deleted"]:
                await publish_event("magnets.purged", {**purged, "ttl_days": TTL_DAYS})
        except Exception:
            log.exception("TTL purge failed after magnet check")


_recheck_codes: set[str] = set()


async def schedule_title_magnet_recheck(code: str) -> None:
    """Re-check one title after a play_timeout (metrics-driven dead-magnet loop)."""
    key = (code or "").strip().upper()
    if not key or key in _recheck_codes:
        return
    _recheck_codes.add(key)

    async def _run() -> None:
        try:
            item = await db_read(db.load_title_for_magnet_check, key)
            if not item:
                return
            outcome = await asyncio.to_thread(_process_title, item)
            await _persist_outcome(item, outcome)
        except Exception:
            log.exception(f"play-triggered magnet recheck failed for {key}")
        finally:
            _recheck_codes.discard(key)

    asyncio.create_task(_run())


async def trigger_check(scope: str = "changed") -> dict[str, Any]:
    """Start a magnet check if none is running. Returns a status dict."""
    global _check_task, _last_progress_push
    async with _check_lock:
        if _check_state["running"] or (_check_task is not None and not _check_task.done()):
            return {
                "status": "running",
                "scope": _check_state["scope"],
                "started_at": _check_state["started_at"],
                "elapsed": round(time.time() - _check_state["started_at"], 1) if _check_state["started_at"] else 0,
            }
        _check_state.update({
            "running": True, "scope": scope, "total": 0, "done": 0,
            "alive": 0, "dead": 0, "swapped": 0, "started_at": time.time(),
        })
        _last_progress_push = 0.0
        _check_task = asyncio.create_task(_run_check_bg(scope))

    try:
        await publish_event("magnets.check_started", {"scope": scope, "started_at": _check_state["started_at"]})
    except Exception:
        log.exception("failed to publish magnets.check_started event")
    return {"status": "started", "scope": scope}


@router.post("/check")
async def start_check(req: CheckRequest) -> JSONResponse:
    """Start a magnet liveness check (background, no duplicate runs)."""
    result = await trigger_check(req.scope)
    status = 200 if result["status"] == "running" else 202
    return JSONResponse(status_code=status, content=result)


@router.get("/check")
async def get_check_status() -> dict[str, Any]:
    """Query magnet check progress."""
    async with _check_lock:
        elapsed = None
        if _check_state["started_at"]:
            elapsed = round(time.time() - _check_state["started_at"], 1)
        return {**_check_state, "elapsed": elapsed}


async def _purge_unplayable(
    engine: Any = None,
    ttl_days: int | None = None,
    reason: str = "dead_magnet",
) -> dict[str, Any]:
    """Delete unplayable titles and seal them in title_blacklist.

    Shared by the manual purge (``ttl_days=None``: everything unplayable) and
    the automatic TTL sweep that runs after a check (``ttl_days=TTL_DAYS``:
    only rows unplayable for at least that long). Liked titles are never
    deleted. Blacklisting stops the next sync from re-downloading the cover
    and re-adding the row; the blacklist retry window still lets a title
    back when its swarm returns.
    """
    from backend.routers.stars import invalidate_stars_cache

    unplayable = await db_read(db.list_unplayable_titles, ttl_days)
    liked = [t for t in unplayable if t["user_liked"]]
    deletable = [t for t in unplayable if not t["user_liked"]]
    if not deletable:
        return {"deleted": 0, "blacklisted": 0, "liked_kept": len(liked),
                "liked_codes": [], "covers_removed": 0, "orphans_removed": 0}

    blacklisted = await db_write(
        db.blacklist_titles,
        [(t["star_id"], t["code"], reason) for t in deletable],
    )
    await db_write(db.delete_titles_by_ids, [t["id"] for t in deletable])

    def _remove_covers() -> int:
        import shutil
        removed = 0
        for t in deletable:
            cover_dir = os.path.join(IMAGES_DIR, t["code"].lower())
            if os.path.isdir(cover_dir):
                shutil.rmtree(cover_dir, ignore_errors=True)
                removed += 1
        return removed

    covers_removed = await asyncio.to_thread(_remove_covers)

    orphans_removed = 0
    if engine is not None:
        try:
            orphans_removed = await asyncio.to_thread(engine.gc_orphaned_torrents)
        except Exception:
            log.exception("gc_orphaned_torrents failed after purge")

    invalidate_stars_cache()
    summary = {
        "deleted": len(deletable),
        "blacklisted": blacklisted,
        "liked_kept": len(liked),
        "liked_codes": [t["code"] for t in liked],
        "covers_removed": covers_removed,
        "orphans_removed": orphans_removed,
    }
    log.info(f"purged unplayable titles (ttl={ttl_days}d): {summary}")
    await publish_event("magnets.purged", {**summary, "ttl_days": ttl_days})
    return summary


@router.post("/purge-dead")
async def purge_dead(request: Request) -> dict[str, Any]:
    """Delete unplayable titles (dead-checked magnets or no magnet at all).

    Liked titles (user_liked=1) are never deleted. Deleted codes are sealed
    in title_blacklist (reason=dead_magnet) so the next sync does not
    re-download and re-add them; the 7-day retry window still lets a title
    back if its swarm comes back to life. Cached torrents of deleted rows
    become orphans and are garbage-collected right away; cover image
    directories are removed as well.

    Unplayable titles are already hidden from /api/stars, so this is the
    manual "reclaim the rows now" switch; the automatic equivalent is the
    TTL sweep that runs after every magnet check (TTL_DAYS).
    """
    async with _check_lock:
        if _check_state["running"]:
            return JSONResponse(
                status_code=409,
                content={"detail": "magnet check is running; purge after it finishes"},
            )

    return await _purge_unplayable(getattr(request.app.state, "engine", None))
