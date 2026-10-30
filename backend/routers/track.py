"""backend/routers/track.py — User behavior tracking (埋点)

Receives batched behavior events from the frontend and persists them to
the user_events table via the serial write queue. Events feed interest
analysis (play / like / view patterns per star and title).
"""

from __future__ import annotations

import asyncio
from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from backend.routers.auth import require_auth
from core import db, get_logger
from core.db.write_queue import db_write
from core.events import publish_event

router = APIRouter(prefix="/api/track", tags=["track"], dependencies=[Depends(require_auth)])
log = get_logger("track")

_METRICS_NOTIFY = frozenset({"play_timeout", "play_error"})


class TrackEvent(BaseModel):
    event: str = Field(..., min_length=1, max_length=64)
    code: str | None = Field(default=None, max_length=64)
    star_code: str | None = Field(default=None, max_length=64)
    meta: dict[str, Any] | None = None


class TrackRequest(BaseModel):
    events: list[TrackEvent] = Field(..., min_length=1, max_length=100)


@router.post("")
async def track_events(request: TrackRequest) -> dict[str, int]:
    """Batch-record user behavior events."""
    inserted = await db_write(
        db.insert_user_events, [e.model_dump() for e in request.events]
    )
    for e in request.events:
        if e.event == "play_timeout" and e.code:
            from backend.routers.magnets import schedule_title_magnet_recheck

            asyncio.create_task(schedule_title_magnet_recheck(e.code))
        if e.event in _METRICS_NOTIFY:
            meta = e.meta or {}
            detail = meta.get("message") or meta.get("reason") or meta.get("error") or ""
            asyncio.create_task(publish_event("metrics.alert", {
                "kind": e.event,
                "code": e.code,
                "star_code": e.star_code,
                "detail": str(detail)[:500] if detail else e.event,
                "meta": {k: v for k, v in meta.items() if k in ("source", "elapsed_ms", "hash")},
            }))
    return {"inserted": inserted}
