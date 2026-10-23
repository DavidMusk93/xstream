from __future__ import annotations

import asyncio
import os
import shutil
from typing import Any
from urllib.parse import parse_qs, urlparse

from fastapi import APIRouter, Request, Depends, HTTPException, Path
from pydantic import BaseModel, Field

from backend.routers.auth import require_auth
from backend.services.magnet_checker import extract_hash
from backend.services.torrent_engine import ADHOC_MARKER
from core import get_logger

log = get_logger("play-router")

router = APIRouter(prefix="/api/play", tags=["play"], dependencies=[Depends(require_auth)])
files_router = APIRouter(prefix="/api/files", tags=["files"], dependencies=[Depends(require_auth)])

HASH_PATTERN = r"^[a-fA-F0-9]{40}$"


class PlayDirectRequest(BaseModel):
    magnet: str = Field(..., min_length=1, max_length=4096)


def get_engine(request: Request) -> Any:
    return request.app.state.engine


def _magnet_display_name(magnet: str) -> str | None:
    """Parse the dn= display name from a magnet URI (may be None)."""
    dn = parse_qs(urlparse(magnet).query).get("dn")
    return dn[0] if dn and dn[0] else None


@router.post("/direct")
async def play_direct(req: PlayDirectRequest, engine: Any = Depends(get_engine)):
    """Play an arbitrary magnet link (ad-hoc play; the torrent is not in the titles DB)."""
    hash_str = extract_hash(req.magnet)
    if not hash_str:
        raise HTTPException(status_code=400, detail="Invalid magnet")

    # add_torrent does synchronous I/O (filesystem scan, libtorrent calls) and
    # already serializes same-hash adds, so re-adding is idempotent.
    try:
        info = await asyncio.to_thread(engine.add_torrent, req.magnet, prefetch=False)
    except Exception as exc:
        log.warning(f"play_direct add_torrent failed: {exc}")
        raise HTTPException(status_code=400, detail="Invalid magnet or unable to add torrent")
    if not info:
        raise HTTPException(status_code=400, detail="Invalid magnet")

    # Pure-disk marker so orphan GC never wipes the ad-hoc cache.
    await asyncio.to_thread(engine.mark_adhoc, hash_str)
    # Start head+window download, same as the play flow after /torrent/add.
    await asyncio.to_thread(engine.resume_download, hash_str, 0, 0)

    status = await asyncio.to_thread(engine.get_status, hash_str)
    return {
        "hash": hash_str,
        "name": _magnet_display_name(req.magnet),
        "status": "added",
        "ready": status["ready"] if status else False,
        "peers": status["peers"] if status else 0,
        "progress": status["progress"] if status else 0.0,
    }


def _scan_adhoc_dirs(engine: Any) -> list[dict[str, Any]]:
    """List ad-hoc cache dirs (marked with a .adhoc file), newest first."""
    items = []
    if not os.path.isdir(engine.cache_dir):
        return items
    for entry in os.scandir(engine.cache_dir):
        if not entry.is_dir() or len(entry.name) != 40:
            continue
        if not os.path.exists(os.path.join(entry.path, ADHOC_MARKER)):
            continue
        # Sparse-file-aware size: allocated blocks, like find_video_state.
        size = 0
        for root, _dirs, files in os.walk(entry.path):
            for f in files:
                try:
                    size += os.stat(os.path.join(root, f)).st_blocks * 512
                except OSError:
                    pass
        try:
            mtime = entry.stat().st_mtime
        except OSError:
            mtime = 0.0
        name = None
        with engine.lock:
            info = engine.torrents.get(entry.name)
        if info:
            if info.get("video_path"):
                name = os.path.basename(info["video_path"])
            else:
                name = _magnet_display_name(info.get("magnet") or "")
        items.append({
            "hash": entry.name,
            "name": name,
            "size_on_disk": size,
            "mtime": mtime,
        })
    items.sort(key=lambda i: i["mtime"], reverse=True)
    return items


@router.get("/recent")
async def play_recent(engine: Any = Depends(get_engine)):
    """List ad-hoc torrent caches, newest first."""
    return {"items": await asyncio.to_thread(_scan_adhoc_dirs, engine)}


@router.delete("/{hash_str}")
async def play_delete(
    hash_str: str = Path(..., pattern=HASH_PATTERN),
    engine: Any = Depends(get_engine),
):
    """Remove an ad-hoc torrent cache."""
    hash_str = hash_str.lower()
    dir_path = os.path.join(engine.cache_dir, hash_str)
    if not os.path.exists(os.path.join(dir_path, ADHOC_MARKER)):
        raise HTTPException(status_code=404, detail="Adhoc torrent not found")
    # Same removal mechanism as /api/cache delete, so eviction/lock bookkeeping
    # stays consistent; fall back to a raw rmtree when the torrent is not loaded.
    removed = await asyncio.to_thread(engine.remove_torrent, hash_str)
    if not removed:
        await asyncio.to_thread(shutil.rmtree, dir_path, True)
    log.info(f"play_delete: removed adhoc {hash_str[:12]}...")
    return {"ok": True}


@files_router.get("/config")
async def files_config():
    """Expose the ostore companion service config to the authed browser.

    The browser fetches this behind the xstream auth cookie, then talks to
    the ostore service directly with the returned token.
    """
    token = os.environ.get("OSTORE_TOKEN")
    if not token:
        raise HTTPException(status_code=503, detail="ostore not configured")
    return {
        "base_url": os.environ.get("OSTORE_PUBLIC_BASE", "/ostore"),
        "token": token,
    }
