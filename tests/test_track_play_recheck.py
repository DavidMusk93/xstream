"""play_timeout events enqueue a single-title magnet recheck (metrics loop)."""

from __future__ import annotations

import os

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.routers.auth import require_auth
from backend.routers import track

pytestmark = pytest.mark.skipif(
    not os.environ.get("XSTREAM_PG_DSN"),
    reason="XSTREAM_PG_DSN not set",
)


@pytest.fixture()
def client(monkeypatch):
    scheduled: list[str] = []

    async def _fake_schedule(code: str) -> None:
        scheduled.append(code)

    monkeypatch.setattr(
        "backend.routers.magnets.schedule_title_magnet_recheck",
        _fake_schedule,
    )
    app = FastAPI()
    app.include_router(track.router)
    app.dependency_overrides[require_auth] = lambda: None
    c = TestClient(app)
    c.scheduled = scheduled  # type: ignore[attr-defined]
    return c


def test_play_timeout_schedules_magnet_recheck(client):
    resp = client.post(
        "/api/track",
        json={"events": [{"event": "play_timeout", "code": "ABC-123", "star_code": "X"}]},
    )
    assert resp.status_code == 200
    assert client.scheduled == ["ABC-123"]  # type: ignore[attr-defined]


def test_other_events_do_not_schedule(client):
    resp = client.post(
        "/api/track",
        json={"events": [{"event": "star_view", "star_code": "X"}]},
    )
    assert resp.status_code == 200
    assert client.scheduled == []  # type: ignore[attr-defined]
