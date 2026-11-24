from __future__ import annotations

import asyncio
from fastapi import APIRouter, Request, Depends, HTTPException, Path
from typing import Any

from backend.models import CacheMetrics
from backend.routers.auth import require_auth
from backend.services import bt_client
from backend.services.torrent_engine import format_size
from core.events import publish_event

router = APIRouter(prefix="/api/cache", tags=["cache"], dependencies=[Depends(require_auth)])

HASH_PATTERN = r"^[a-fA-F0-9]{40}$"


def get_engine(request: Request) -> Any:
    return request.app.state.engine


@router.get("")
async def get_cache(engine: Any = Depends(get_engine)):
    """Get all cache items known to the engine.

    Previously filtered by local_size > 0, which hid newly-added or paused
    torrents that had metadata but no downloaded data yet. Show everything
    with a known video file so the manager is useful immediately.
    """
    if bt_client.is_enabled():
        return await bt_client.cache_list()
    all_items = await asyncio.to_thread(engine.get_all_status)
    items = [i for i in all_items if i and i.get("video_size", 0) > 0]
    total_disk = await asyncio.to_thread(engine._get_cache_size)
    return {
        "totalSize": total_disk,
        "maxSize": engine.max_size_bytes,
        "itemCount": len(items),
        "items": items,
    }


@router.delete("/{hash_str}")
async def delete_cache(
    hash_str: str = Path(..., pattern=HASH_PATTERN),
    engine: Any = Depends(get_engine),
):
    """Remove a torrent from cache."""
    if bt_client.is_enabled():
        res = await bt_client.cache_delete(hash_str)
        await publish_event("cache.update", {"action": "delete", "hash": hash_str})
        return res
    success = await asyncio.to_thread(engine.remove_torrent, hash_str)
    if not success:
        raise HTTPException(status_code=404, detail="Torrent not found")
    await publish_event("cache.update", {"action": "delete", "hash": hash_str})
    return {"deleted": True}


@router.post("/gc-orphans")
async def gc_orphans(engine: Any = Depends(get_engine)):
    """Manually trigger orphan torrent GC / quota eviction."""
    if bt_client.is_enabled():
        res = await bt_client.cache_evict()
        removed = len(res.get("evicted_hashes", []))
        await publish_event("cache.update", {"action": "gc", "removed": removed})
        return {"removed": removed, **res}
    removed = await asyncio.to_thread(engine.gc_orphaned_torrents)
    await publish_event("cache.update", {"action": "gc", "removed": removed})
    return {"removed": removed}


@router.get("/metrics", response_model=CacheMetrics)
async def get_metrics(engine: Any = Depends(get_engine)):
    """Get cache metrics summary."""
    if bt_client.is_enabled():
        return CacheMetrics(**(await bt_client.cache_metrics()))
    all_items = await asyncio.to_thread(engine.get_all_status)
    items = [i for i in all_items if i and i.get("video_size", 0) > 0]
    total_disk = await asyncio.to_thread(engine._get_cache_size)
    completed = sum(1 for i in items if i.get("progress", 0) >= 99.9)
    return CacheMetrics(
        total=len(items),
        completed=completed,
        downloading=len(items) - completed,
        used_bytes=total_disk,
        used_human=format_size(total_disk),
        max_bytes=engine.max_size_bytes,
        max_human=format_size(engine.max_size_bytes),
    )
