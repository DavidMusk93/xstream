"""Locks notify registry, tg-lint/fallback render, and dispatch gates."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from backend.services import notify
from backend.services.notify.registry import DEFAULT_EVENTS


def test_default_events_include_library_and_metrics(monkeypatch):
    monkeypatch.delenv("XSTREAM_NOTIFY_EVENTS", raising=False)
    cfg = notify.notify_config()
    assert "sync.completed" in cfg["events"]
    assert "metrics.alert" in cfg["events"]
    assert "torrent.progress" not in DEFAULT_EVENTS


def test_star_updates_plain_format():
    from backend.services.notify.fallback import format_plain

    text = format_plain("sync.completed", {
        "total_new": 1,
        "total_updated": 0,
        "elapsed": 9,
        "star_updates": [{
            "name": "Demo",
            "code": "D1",
            "count": 1,
            "new_titles": [{"code": "ABC-1", "title": "Hello"}],
        }],
        "failed": [],
    })
    assert "ABC-1" in text
    assert "Demo" in text


@pytest.mark.asyncio
async def test_dispatch_skips_when_disabled(monkeypatch):
    monkeypatch.setenv("XSTREAM_NOTIFY_ENABLED", "0")
    called: list[str] = []

    async def fake_send(chunks, *, parse_mode):
        called.extend(chunks)

    monkeypatch.setattr(notify.telegram_mod, "send_messages", fake_send)
    await notify.dispatch("sync.completed", {"total_new": 0, "elapsed": 1})
    assert called == []


@pytest.mark.asyncio
async def test_render_html_when_tg_lint_missing(monkeypatch):
    monkeypatch.setenv("XSTREAM_TG_LINT", "/nonexistent/tg-lint")
    from backend.services.notify import render as render_mod

    text, mode = await render_mod.render("sync.completed", {
        "total_new": 1,
        "total_updated": 0,
        "elapsed": 1,
        "trigger": "test",
        "star_updates": [],
        "failed": [],
    })
    assert mode == "HTML"
    assert "<b>" in text


@pytest.mark.asyncio
async def test_dispatch_sends_when_configured(monkeypatch):
    monkeypatch.setenv("XSTREAM_TELEGRAM_BOT_TOKEN", "test-token")
    monkeypatch.setenv("XSTREAM_TELEGRAM_CHAT_ID", "123")
    monkeypatch.setenv("XSTREAM_NOTIFY_EVENTS", "sync.error")
    sent: list[str] = []

    async def fake_send(chunks, *, parse_mode):
        sent.extend(chunks)

    monkeypatch.setattr(notify.telegram_mod, "send_messages", fake_send)
    await notify.dispatch("sync.error", {"error": "boom", "trigger": "manual", "elapsed": 1})
    assert len(sent) == 1
    assert "boom" in sent[0]


def test_tg_lint_sync_completed_binary():
    lint = Path(__file__).resolve().parents[1] / "tools" / "tg-lint" / "target" / "release" / "tg-lint"
    if not lint.is_file():
        pytest.skip("tg-lint not built (cargo build --release -p tg-lint)")
    payload = {
        "event": "sync.completed",
        "data": {
            "total_new": 1,
            "total_updated": 0,
            "elapsed": 12.3,
            "trigger": "scheduled",
            "star_updates": [{
                "code": "X",
                "name": "Star",
                "count": 1,
                "new_titles": [{"code": "ABC-100", "title": "Nice", "date": "01/01/2026"}],
            }],
            "failed": [],
        },
    }
    proc = subprocess.run(
        [str(lint)],
        input=json.dumps(payload).encode(),
        capture_output=True,
        timeout=5,
        check=True,
    )
    out = proc.stdout.decode()
    assert "Library sync" in out
    assert "ABC-100" in out
    assert "<b>" in out
