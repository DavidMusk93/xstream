"""backend/routers/social.py — Injected X (Twitter) profiles for stars

xstream never calls the X API (paid, unstable). An agent browsing x.com —
or the owner — injects what it sees; see docs/design/x-inject.md.

  GET  /api/social/x/pending   which stars still need a check (agent to-do list)
  POST /api/social/x           inject HTML / text / JSON for one star or a batch
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from backend.routers.auth import require_auth
from backend.routers.stars import invalidate_stars_cache
from backend.services.x_inject import InjectError, XPost, parse_payload
from core import db, get_logger
from core.db.write_queue import db_read, db_write
from core.events import publish_event

log = get_logger("social-router")
router = APIRouter(prefix="/api/social", tags=["social"], dependencies=[Depends(require_auth)])

MAX_PAYLOAD_CHARS = 2_000_000
MAX_BATCH = 100

INJECT_HELP = {
    "endpoint": "POST /api/social/x",
    "body": {"star": "<code|name, optional for batch>", "content": "<x.com HTML | text | JSON>"},
    "json_single": {
        "handle": "username (null = no X account)",
        "name": "display name", "avatar": "https://pbs.twimg.com/profile_images/...",
        "posts": [{"url": "https://x.com/<user>/status/<id>", "text": "...",
                   "posted_at": "ISO-8601", "media": ["https://pbs.twimg.com/media/..."],
                   "likes": 0, "reposts": 0, "replies": 0, "views": 0}],
    },
    "json_batch": {"stars": [{"star": "<code|name>", "handle": "...", "posts": []}]},
    "text": "@handle line, then posts separated by '---' lines (status URL + text); 'none' = no account",
    "keep": "newest 5 posts per star; posts merge by id across injects",
}


class InjectRequest(BaseModel):
    star: str | None = Field(default=None, max_length=120)
    content: str | dict[str, Any] | list[Any]


def _post_dict(p: XPost) -> dict[str, Any]:
    return {
        "id": p.id, "text": p.text, "url": p.url, "posted_at": p.posted_at,
        "media": p.media, "stats": p.stats, "pinned": p.pinned, "author": p.author,
    }


@router.get("/x/pending")
async def x_pending(stale_hours: int = Query(default=72, ge=0, le=24 * 365)) -> dict[str, Any]:
    """Stars never checked or checked longer than stale_hours ago (bound accounts first)."""
    rows = await db_read(db.list_x_status)
    cutoff = datetime.now(UTC).replace(tzinfo=None) - timedelta(hours=stale_hours)
    pending = [
        {
            "star": code,
            "name": name,
            "jp": jp or "",
            "handle": handle,
            "checked_at": checked_at.strftime("%Y-%m-%dT%H:%M:%SZ") if checked_at else None,
            "posts": posts,
        }
        for code, name, jp, handle, checked_at, posts in rows
        if checked_at is None or checked_at < cutoff
    ]
    return {"count": len(pending), "stars": pending, "inject": INJECT_HELP}


@router.post("/x")
async def inject_x(request: InjectRequest) -> dict[str, Any]:
    """Parse and store injected X content; returns per-star results."""
    content = request.content
    if isinstance(content, str) and len(content) > MAX_PAYLOAD_CHARS:
        raise HTTPException(status_code=413, detail="payload too large (max 2MB)")
    try:
        # HTML parsing of a full x.com page is CPU-heavy; keep it off the loop.
        profiles = await asyncio.to_thread(parse_payload, content, request.star)
    except InjectError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None
    if len(profiles) > MAX_BATCH:
        raise HTTPException(status_code=413, detail=f"batch too large (max {MAX_BATCH})")

    results: list[dict[str, Any]] = []
    for prof in profiles:
        if not prof.star:
            results.append({"star": None, "ok": False, "error": "no target star"})
            continue
        found = await db_read(db.find_star, prof.star)
        if not found:
            results.append({"star": prof.star, "ok": False, "error": "star not found"})
            continue
        star_id, code, name = found
        stored = await db_write(
            db.save_x_profile,
            star_id, prof.handle, prof.name, prof.avatar,
            [_post_dict(p) for p in prof.posts], prof.not_found,
        )
        results.append({
            "star": code, "name": name, "ok": True,
            "handle": stored["handle"], "posts": len(stored["posts"]),
            "received": len(prof.posts),
        })
        log.info(f"x inject: {code} handle={stored['handle']} posts={len(stored['posts'])}")

    updated = [r for r in results if r["ok"]]
    if updated:
        invalidate_stars_cache()
        await publish_event("star.social", {"stars": [r["star"] for r in updated]})
    if not updated and results:
        raise HTTPException(status_code=404, detail=results[0]["error"])
    return {"updated": len(updated), "results": results}
