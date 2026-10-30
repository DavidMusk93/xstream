"""Outbound notifications — registry hooks on core.events.publish_event."""

from __future__ import annotations

import asyncio
import os
import time
from typing import Any

from backend.services.notify.registry import CATALOG, DEFAULT_EVENTS, HOOKS
from backend.services.notify import render as render_mod
from backend.services.notify import telegram as telegram_mod
from backend.services.notify.fallback import format_html
from core.logger import get_logger

log = get_logger("notify")

__all__ = [
    "CATALOG",
    "DEFAULT_EVENTS",
    "HOOKS",
    "dispatch",
    "is_enabled_for",
    "notify_config",
    "schedule_dispatch",
    "send_test_message",
]


def _parse_events(raw: str | None) -> frozenset[str]:
    if not raw or not raw.strip():
        return DEFAULT_EVENTS
    s = raw.strip()
    if s == "*":
        return frozenset(CATALOG)
    return frozenset(x.strip() for x in s.split(",") if x.strip())


def notify_config() -> dict[str, Any]:
    enabled_flag = (os.environ.get("XSTREAM_NOTIFY_ENABLED") or "auto").strip().lower()
    configured = telegram_mod.telegram_configured()
    if enabled_flag in ("0", "false", "off"):
        active = False
    elif enabled_flag in ("1", "true", "on"):
        active = configured
    else:
        active = configured
    lint = render_mod.tg_lint_path()
    return {
        "enabled": active,
        "telegram_configured": configured,
        "tg_lint": str(lint) if lint else None,
        "events": sorted(_parse_events(os.environ.get("XSTREAM_NOTIFY_EVENTS"))),
        "catalog": CATALOG,
        "hooks": [{"event": h.event, "description": h.description, "default": h.default} for h in HOOKS],
    }


def is_enabled_for(event: str) -> bool:
    cfg = notify_config()
    return cfg["enabled"] and event in cfg["events"]


def schedule_dispatch(event: str, data: dict[str, Any]) -> None:
    if not is_enabled_for(event):
        return
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return
    loop.create_task(_dispatch_safe(event, data))


async def _dispatch_safe(event: str, data: dict[str, Any]) -> None:
    try:
        await dispatch(event, data)
    except Exception:
        log.exception(f"notify dispatch failed for {event}")


async def dispatch(event: str, data: dict[str, Any]) -> None:
    if not is_enabled_for(event):
        return
    text, parse_mode = await render_mod.render(event, data)
    if not text:
        return
    chunks = telegram_mod.split_message(text, parse_mode=parse_mode)
    await telegram_mod.send_messages(chunks, parse_mode=parse_mode)


async def send_test_message() -> None:
    ts = time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime())
    sample = {
        "total_new": 2,
        "total_updated": 1,
        "elapsed": 42.5,
        "trigger": "test",
        "star_updates": [{
            "code": "DEMO",
            "name": "Demo Star",
            "count": 2,
            "new_titles": [
                {"code": "ABC-001", "title": "Sample work title", "date": "01/15/2026", "resolution": "4K", "size": "5.2GB"},
                {"code": "ABC-002", "title": "Another release", "date": "01/20/2026", "resolution": "1080p", "size": "4.1GB"},
            ],
        }],
        "failed": [],
    }
    text, parse_mode = await render_mod.render("sync.completed", sample)
    if not text:
        text = format_html("sync.completed", sample)
        parse_mode = "HTML"
    safe_ts = ts.replace("&", "&amp;")
    header = f"🧪 <b>Notify test</b> · <i>{safe_ts}</i>\n\n"
    await telegram_mod.send_messages(
        telegram_mod.split_message(header + text, parse_mode=parse_mode),
        parse_mode=parse_mode,
    )
