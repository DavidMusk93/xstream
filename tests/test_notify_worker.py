"""Locks NotifyWorker durability: chunk resume, 429 Retry-After, HTML fallback, dead-letter."""

from __future__ import annotations

import httpx
import pytest

from backend.services.notify import telegram as tg
from backend.services.notify.worker import NotifyWorker
from core import db


@pytest.mark.asyncio
async def test_worker_chunk_resume_after_timeout(pg_test_db, monkeypatch):
    """If chunk 1 succeeds and chunk 2 times out, retry resumes at chunk 2 without duplicates."""
    oid = db.enqueue_notification("sync.completed", ["card-1", "card-2", "card-3"], "HTML")

    calls: list[str] = []
    fail_once = {"done": False}

    async def fake_send_chunk(client, text, *, parse_mode):
        calls.append(text)
        if text == "card-2" and not fail_once["done"]:
            fail_once["done"] = True
            return tg.TelegramDeliveryOutcome(ok=False, retryable=True, error="ReadTimeout")
        return tg.TelegramDeliveryOutcome(ok=True)

    monkeypatch.setattr(tg, "send_chunk", fake_send_chunk)

    worker = NotifyWorker(min_send_interval=0.0, backoff_schedule=(0.0,))
    await worker.process_once()

    # First attempt sent card-1, failed on card-2 -> paused with sent_chunks=1
    assert calls == ["card-1", "card-2"]
    stats = db.get_notify_outbox_stats()
    assert stats["pending"] == 1
    assert stats["sent"] == 0

    # Second attempt resumes at card-2 and finishes card-3 (card-1 is NOT resent)
    await worker.process_once()
    assert calls == ["card-1", "card-2", "card-2", "card-3"]
    stats2 = db.get_notify_outbox_stats()
    assert stats2["pending"] == 0
    assert stats2["sent"] == 1
    assert db.fetch_due_notifications() == []
    if worker._client:
        await worker._client.aclose()


@pytest.mark.asyncio
async def test_worker_respects_429_retry_after(pg_test_db, monkeypatch):
    """HTTP 429 schedules next_retry_at using Telegram's retry_after value."""
    db.enqueue_notification("sync.completed", ["card-1"], "HTML")

    async def fake_send_chunk(client, text, *, parse_mode):
        return tg.TelegramDeliveryOutcome(
            ok=False, retryable=True, retry_after=12.0, error="HTTP 429"
        )

    monkeypatch.setattr(tg, "send_chunk", fake_send_chunk)

    worker = NotifyWorker(min_send_interval=0.0, backoff_schedule=(1.0,))
    await worker.process_once()

    # Not due immediately; delay reflects retry_after (~12.5s)
    assert db.fetch_due_notifications() == []
    delay = db.next_pending_delay()
    assert delay is not None and delay >= 10.0
    if worker._client:
        await worker._client.aclose()


@pytest.mark.asyncio
async def test_worker_dead_letters_permanent_error(pg_test_db, monkeypatch):
    """Non-retryable errors (e.g. HTTP 401/403) immediately move the row to dead."""
    db.enqueue_notification("sync.error", ["boom"], "HTML")

    async def fake_send_chunk(client, text, *, parse_mode):
        return tg.TelegramDeliveryOutcome(ok=False, retryable=False, error="HTTP 401: Unauthorized")

    monkeypatch.setattr(tg, "send_chunk", fake_send_chunk)

    worker = NotifyWorker(min_send_interval=0.0)
    await worker.process_once()

    stats = db.get_notify_outbox_stats()
    assert stats["pending"] == 0
    assert stats["dead"] == 1
    assert "401" in stats["recent_errors"][0]["last_error"]
    if worker._client:
        await worker._client.aclose()


@pytest.mark.asyncio
async def test_worker_dead_letters_after_max_attempts(pg_test_db, monkeypatch):
    """Repeated retryable failures dead-letter once max_attempts is reached."""
    db.enqueue_notification("sync.error", ["boom"], "HTML")

    async def fake_send_chunk(client, text, *, parse_mode):
        return tg.TelegramDeliveryOutcome(ok=False, retryable=True, error="HTTP 502: Bad Gateway")

    monkeypatch.setattr(tg, "send_chunk", fake_send_chunk)

    worker = NotifyWorker(min_send_interval=0.0, max_attempts=2, backoff_schedule=(0.0,))
    await worker.process_once()
    assert db.get_notify_outbox_stats()["pending"] == 1

    await worker.process_once()
    stats = db.get_notify_outbox_stats()
    assert stats["pending"] == 0
    assert stats["dead"] == 1
    assert stats["recent_errors"][0]["attempts"] == 2
    if worker._client:
        await worker._client.aclose()


@pytest.mark.asyncio
async def test_send_chunk_html_parse_error_falls_back_to_plain(monkeypatch):
    """HTTP 400 entity parse error retries once as plain text without failing."""
    monkeypatch.setenv("XSTREAM_TELEGRAM_BOT_TOKEN", "tok")
    monkeypatch.setenv("XSTREAM_TELEGRAM_CHAT_ID", "42")

    seen_payloads: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        import json

        body = json.loads(request.content.decode())
        seen_payloads.append(body)
        if body.get("parse_mode") == "HTML":
            return httpx.Response(
                400,
                json={"ok": False, "description": "Bad Request: can't parse entities: Unexpected end tag"},
            )
        return httpx.Response(200, json={"ok": True, "result": {"message_id": 1}})

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        outcome = await tg.send_chunk(client, "<b>broken", parse_mode="HTML")

    assert outcome.ok is True
    assert len(seen_payloads) == 2
    assert seen_payloads[0].get("parse_mode") == "HTML"
    assert "parse_mode" not in seen_payloads[1]
    assert seen_payloads[1]["text"] == "broken"
