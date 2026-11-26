"""backend/routers/notify.py — Operator notification config (Telegram)

  GET  /api/notify/status  configured events (no secrets)
  POST /api/notify/test    send a test Telegram message
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from backend.routers.auth import require_auth
from backend.services import notify
from core import db
from core.db.write_queue import db_read

router = APIRouter(prefix="/api/notify", tags=["notify"], dependencies=[Depends(require_auth)])


@router.get("/status")
async def notify_status() -> dict:
    cfg = notify.notify_config()
    cfg["worker_running"] = notify.get_worker().running
    try:
        cfg["outbox"] = await db_read(db.get_notify_outbox_stats)
    except Exception:
        cfg["outbox"] = None
    return cfg


@router.post("/test")
async def notify_test() -> dict:
    cfg = notify.notify_config()
    if not cfg["telegram_configured"]:
        raise HTTPException(
            status_code=503,
            detail="Set XSTREAM_TELEGRAM_BOT_TOKEN and XSTREAM_TELEGRAM_CHAT_ID in /etc/xstream.env",
        )
    await notify.send_test_message()
    return {"ok": True, "sent": True}
