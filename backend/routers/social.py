"""backend/routers/social.py — Injected X (Twitter) profiles

xstream never calls the X API (paid, unstable). An agent browsing x.com —
or the owner — injects what it sees; see docs/design/x-inject.md.

  GET    /api/social/x/pending          which stars still need a check (agent to-do list)
  POST   /api/social/x                  inject HTML / text / JSON for one star or a batch
  POST   /api/social/x/creators         inject pornographic creators (owner's X follows)
  DELETE /api/social/x/creators/{handle}  unfollow a pornographic creator
  GET    /api/social/x/media/{filename} injected X images, served from the local cache
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Request
from fastapi.responses import RedirectResponse, Response
from pydantic import BaseModel, Field

from backend.routers.auth import require_auth
from backend.routers.stars import invalidate_stars_cache
from backend.services import x_media
from backend.services.x_inject import InjectError, XPost, parse_payload
from core import db, get_logger
from core.db.write_queue import db_read, db_write
from core.events import publish_event

log = get_logger("social-router")
router = APIRouter(prefix="/api/social", tags=["social"], dependencies=[Depends(require_auth)])

MAX_PAYLOAD_CHARS = 2_000_000
MAX_BATCH = 100

CREATOR_HELP = {
    "endpoint": "POST /api/social/x/creators",
    "body": {"content": "<x.com HTML | text | JSON>"},
    "json_batch": {"creators": [{
        "handle": "<username>", "name": "display name",
        "avatar": "https://pbs.twimg.com/profile_images/...",
        "posts": [{"url": "https://x.com/<user>/status/<id>", "text": "...",
                   "posted_at": "ISO-8601", "media": ["https://pbs.twimg.com/media/..."],
                   "likes": 0, "reposts": 0, "replies": 0, "views": 0,
                   "en": "concise, cute, flirty English translation"}],
    }]},
    "json_single": {"handle": "<username>", "name": "...", "posts": []},
    "text": "@handle line, then posts separated by '---' lines",
    "keep": "newest 10 posts per creator; posts merge by id across injects",
    "scope": (
        "pornographic creators: X accounts the owner follows for adult content — "
        "NOT library stars (no code/titles), keyed by handle"
    ),
    "batch": "prefer one POST with {\"creators\": [...]} — many creators per run",
    "follow_list": {
        "ostore_path": "meta/x-pornographic-creators.txt",
        "format": "one handle per line (@ optional); agents refresh from owner's X Following",
    },
}

INJECT_HELP = {
    "endpoint": "POST /api/social/x",
    "body": {"star": "<code|name, optional for batch>", "content": "<x.com HTML | text | JSON>"},
    "json_single": {
        "handle": "username (null = no X account)",
        "name": "display name", "avatar": "https://pbs.twimg.com/profile_images/...",
        "posts": [{"url": "https://x.com/<user>/status/<id>", "text": "...",
                   "posted_at": "ISO-8601", "media": ["https://pbs.twimg.com/media/..."],
                   "likes": 0, "reposts": 0, "replies": 0, "views": 0,
                   "en": "concise, cute, flirty English translation"}],
    },
    "json_batch": {"stars": [{"star": "<code|name>", "handle": "...", "posts": []}]},
    "text": "@handle line, then posts separated by '---' lines (status URL + text); 'none' = no account",
    "keep": "newest 5 posts per star; posts merge by id across injects",
    "translate": "send {url, en} only to add a translation to a stored post",
    "creators": (
        "pornographic creators (owner's adult-content X follows, not library stars): "
        "POST /api/social/x/creators with {\"creators\": [...]}, 10 posts each, batch preferred"
    ),
}


class InjectRequest(BaseModel):
    star: str | None = Field(default=None, max_length=120)
    content: str | dict[str, Any] | list[Any]


def _post_dict(p: XPost) -> dict[str, Any]:
    return {
        "id": p.id, "text": p.text, "url": p.url, "posted_at": p.posted_at,
        "media": p.media, "stats": p.stats, "pinned": p.pinned, "author": p.author, "en": p.en,
    }


@router.get("/x/agent-brief")
async def x_agent_brief(
    request: Request,
    stale_hours: int = Query(default=72, ge=0, le=24 * 365),
) -> dict[str, Any]:
    """Self-bootstrap for external agents: work queue + schemas + copy-paste prompt.

    Authenticated agents call this once per run instead of reading repo docs.
    The web Inject sheet's "Copy agent brief" uses the same payload.
    """
    from backend.services.x_agent_brief import build_x_agent_brief

    star_rows = await db_read(db.list_x_status)
    creators = await db_read(db.load_creators)
    origin = str(request.base_url).rstrip("/")
    return build_x_agent_brief(
        origin=origin,
        star_rows=star_rows,
        creators=creators,
        stale_hours=stale_hours,
        inject_help=INJECT_HELP,
        creator_help=CREATOR_HELP,
    )


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


# Cached X images are immutable per URL — let browsers/Caddy hold them.
_MEDIA_CACHE_HEADERS = {"Cache-Control": "public, max-age=2592000, immutable"}

_MIME_BY_EXT = {
    "jpg": "image/jpeg",
    "png": "image/png",
    "webp": "image/webp",
    "gif": "image/gif",
}


@router.get("/x/media/{filename}")
async def x_media_file(filename: str, u: str = Query(default="")) -> Response:
    """Serve an injected X image from the local cache (see services/x_media.py).

    Disk hit -> 307 to /images/x/{filename} so Caddy serves it statically.
    Miss -> download the original `u` (twimg only), cache it, serve the bytes.
    """
    if not x_media.valid_filename(filename):
        raise HTTPException(status_code=404, detail="not found")
    path = await asyncio.to_thread(x_media.cached_path, filename)
    if path:
        return RedirectResponse(
            url=f"/images/x/{filename}", status_code=307, headers=_MEDIA_CACHE_HEADERS
        )
    if not u or not x_media.validate_source(u):
        raise HTTPException(status_code=400, detail="invalid source url")
    path = await x_media.fetch_to_cache(u)
    if not path or path.name != filename:
        raise HTTPException(status_code=502, detail="fetch failed")
    return Response(
        content=path.read_bytes(),
        media_type=_MIME_BY_EXT.get(path.suffix.lstrip("."), "image/jpeg"),
        headers=_MEDIA_CACHE_HEADERS,
    )


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
        # Prefetch images into images/x/ so the first view hits local disk.
        warm_urls = [stored.get("avatar") or prof.avatar]
        for p in stored["posts"]:
            warm_urls.extend(p.get("media") or [])
        asyncio.create_task(x_media.warm(warm_urls))

    updated = [r for r in results if r["ok"]]
    if updated:
        invalidate_stars_cache()
        await publish_event("star.social", {"stars": [r["star"] for r in updated]})
    if not updated and results:
        raise HTTPException(status_code=404, detail=results[0]["error"])
    return {"updated": len(updated), "results": results}


# ── Body creators ────────────────────────────────────────────────────

class CreatorInjectRequest(BaseModel):
    content: str | dict[str, Any] | list[Any]


@router.get("/x/creators")
async def list_creators() -> dict[str, Any]:
    """Every injected body creator with its newest posts (agent to-do list)."""
    creators = await db_read(db.load_creators)
    for c in creators:
        if c.get("avatar"):
            c["avatar"] = x_media.proxy_url(c["avatar"])
        for post in c.get("posts", []):
            post["media"] = [x_media.proxy_url(u) for u in post.get("media") or []]
    return {"count": len(creators), "creators": creators, "inject": CREATOR_HELP}


@router.post("/x/creators")
async def inject_creators(request: CreatorInjectRequest) -> dict[str, Any]:
    """Inject one creator's X timeline (or a batch of creators).

    Creators are accounts the owner follows on X that are not library stars:
    they live in body_creators / creator_posts, never in stars, and keep the
    newest 10 posts each. The external bot drives this endpoint.
    """
    content = request.content
    if isinstance(content, str) and len(content) > MAX_PAYLOAD_CHARS:
        raise HTTPException(status_code=413, detail="payload too large (max 2MB)")
    try:
        profiles = await asyncio.to_thread(parse_payload, content, None, True)
    except InjectError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None
    if len(profiles) > MAX_BATCH:
        raise HTTPException(status_code=413, detail=f"batch too large (max {MAX_BATCH})")

    results: list[dict[str, Any]] = []
    warm_urls: list[str | None] = []
    for prof in profiles:
        handle = prof.handle
        if not handle:
            results.append({"handle": None, "ok": False, "error": "no X handle"})
            continue
        try:
            stored = await db_write(
                db.save_creator_profile,
                handle, prof.name, prof.avatar,
                [_post_dict(p) for p in prof.posts], prof.not_found,
            )
        except LookupError as exc:
            results.append({"handle": handle, "ok": False, "error": str(exc)})
            continue
        results.append({
            "handle": stored["handle"], "ok": True,
            "posts": len(stored["posts"]), "received": len(prof.posts),
        })
        warm_urls.append(prof.avatar)
        for p in stored["posts"]:
            warm_urls.extend(p.get("media") or [])

    updated = [r for r in results if r["ok"]]
    if warm_urls:
        asyncio.create_task(x_media.warm(warm_urls))
    if updated:
        invalidate_stars_cache()
        await publish_event("creator.social", {"handles": [r["handle"] for r in updated]})
        log.info(f"creator inject: {len(updated)} creator(s)")
    if not updated and results:
        raise HTTPException(status_code=422, detail=results[0]["error"])
    return {"updated": len(updated), "results": results}


@router.delete("/x/creators/{handle}")
async def unfollow_creator(
    handle: str = Path(..., pattern=r"^[A-Za-z0-9_]{1,15}$"),
) -> dict[str, Any]:
    """Unfollow a body creator: drop the account and all its stored posts."""
    deleted = await db_write(db.delete_creator, handle)
    if not deleted:
        raise HTTPException(status_code=404, detail="creator not found")
    invalidate_stars_cache()
    await publish_event("creator.social", {"handles": [handle], "removed": True})
    log.info(f"creator removed: {handle}")
    return {"handle": handle, "deleted": True}
