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
from backend.services.notify.worker import NotifyWorker
from core import db
from core.db.write_queue import db_write
from core.logger import get_logger

log = get_logger("notify")

__all__ = [
    "CATALOG",
    "DEFAULT_EVENTS",
    "HOOKS",
    "NotifyWorker",
    "dispatch",
    "enqueue",
    "get_worker",
    "is_enabled_for",
    "notify_config",
    "schedule_dispatch",
    "send_test_message",
    "start_worker",
    "stop_worker",
]

_worker = NotifyWorker()
_enqueue_tasks: set[asyncio.Task[Any]] = set()
_cfg_cache_key: tuple[str, ...] | None = None
_cfg_cache_val: dict[str, Any] | None = None
_cfg_events_set: frozenset[str] = DEFAULT_EVENTS


def get_worker() -> NotifyWorker:
    return _worker


def start_worker() -> None:
    """Start the durable outbox delivery worker (called from FastAPI lifespan)."""
    _worker.start()


async def stop_worker(drain_timeout: float = 5.0) -> None:
    """Wait for pending enqueue tasks and gracefully stop the delivery worker."""
    if _enqueue_tasks:
        pending = list(_enqueue_tasks)
        await asyncio.wait(pending, timeout=min(2.0, drain_timeout))
    await _worker.stop(drain_timeout=drain_timeout)


def _parse_events(raw: str | None) -> frozenset[str]:
    if not raw or not raw.strip():
        return DEFAULT_EVENTS
    s = raw.strip()
    if s == "*":
        return frozenset(CATALOG)
    return frozenset(x.strip() for x in s.split(",") if x.strip())


def _env_key() -> tuple[str, ...]:
    return (
        os.environ.get("XSTREAM_NOTIFY_ENABLED") or "",
        os.environ.get("XSTREAM_NOTIFY_EVENTS") or "",
        os.environ.get("XSTREAM_TELEGRAM_BOT_TOKEN") or "",
        os.environ.get("TELEGRAM_BOT_TOKEN") or "",
        os.environ.get("XSTREAM_TELEGRAM_CHAT_ID") or "",
        os.environ.get("TELEGRAM_CHAT_ID") or "",
        os.environ.get("XSTREAM_TG_LINT") or "",
    )


def notify_config() -> dict[str, Any]:
    global _cfg_cache_key, _cfg_cache_val, _cfg_events_set
    key = _env_key()
    if key == _cfg_cache_key and _cfg_cache_val is not None:
        return dict(_cfg_cache_val)

    enabled_flag = (os.environ.get("XSTREAM_NOTIFY_ENABLED") or "auto").strip().lower()
    configured = telegram_mod.telegram_configured()
    if enabled_flag in ("0", "false", "off"):
        active = False
    elif enabled_flag in ("1", "true", "on"):
        active = configured
    else:
        active = configured
    lint = render_mod.tg_lint_path()
    events_set = _parse_events(os.environ.get("XSTREAM_NOTIFY_EVENTS"))
    cfg = {
        "enabled": active,
        "telegram_configured": configured,
        "tg_lint": str(lint) if lint else None,
        "events": sorted(events_set),
        "catalog": CATALOG,
        "hooks": [{"event": h.event, "description": h.description, "default": h.default} for h in HOOKS],
    }
    _cfg_cache_key = key
    _cfg_cache_val = cfg
    _cfg_events_set = events_set
    return dict(cfg)


def is_enabled_for(event: str) -> bool:
    cfg = notify_config()
    return bool(cfg["enabled"]) and event in _cfg_events_set


def schedule_dispatch(event: str, data: dict[str, Any]) -> None:
    if not is_enabled_for(event):
        return
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return
    task = loop.create_task(_dispatch_safe(event, data), name=f"notify-enqueue:{event}")
    _enqueue_tasks.add(task)
    task.add_done_callback(_enqueue_tasks.discard)


async def _dispatch_safe(event: str, data: dict[str, Any]) -> None:
    try:
        await dispatch(event, data)
    except Exception:
        log.exception(f"notify dispatch failed for {event}")


async def enqueue(event: str, data: dict[str, Any]) -> int | None:
    """Render an event and persist its chunks into notify_outbox, then wake the worker."""
    if not is_enabled_for(event):
        return None
    text, parse_mode = await render_mod.render(event, data)
    if not text:
        return None
    chunks = telegram_mod.split_message(text, parse_mode=parse_mode)
    if not chunks:
        return None
    outbox_id = await db_write(db.enqueue_notification, event, chunks, parse_mode)
    log.info(f"notify enqueued: id={outbox_id} event={event} chunks={len(chunks)}")
    _worker.wake()
    return outbox_id


async def dispatch(event: str, data: dict[str, Any]) -> None:
    """Enqueue into the durable outbox when the worker is active; else direct send."""
    if not is_enabled_for(event):
        return
    if _worker.running:
        await enqueue(event, data)
        return
    text, parse_mode = await render_mod.render(event, data)
    if not text:
        return
    chunks = telegram_mod.split_message(text, parse_mode=parse_mode)
    await telegram_mod.send_messages(chunks, parse_mode=parse_mode)


async def send_test_message() -> None:
    ts = time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime())
    domain = os.environ.get("XSTREAM_DOMAIN") or "cc.guohuasun.com"
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
                {
                    "code": "ABF-137",
                    "title": "Let's Make A Baby? 4 Situations Where The Uterus Begs For Creampie",
                    "date": "01/15/2026",
                    "resolution": "4K",
                    "size": "5.2GB",
                    "cover_url": f"https://{domain}/images/titles/abf-137/abf-137.jpg",
                },
                {
                    "code": "ABC-002",
                    "title": "Another release with English description",
                    "date": "01/20/2026",
                    "resolution": "1080p",
                    "size": "4.1GB",
                },
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
