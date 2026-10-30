"""backend/routers/notify.py — Operator notification config (Telegram)

  GET  /api/notify/status  configured events (no secrets)
  POST /api/notify/test    send a test Telegram message
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from backend.routers.auth import require_auth
from backend.services import notify

router = APIRouter(prefix="/api/notify", tags=["notify"], dependencies=[Depends(require_auth)])


@router.get("/status")
async def notify_status() -> dict:
    return notify.notify_config()


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
