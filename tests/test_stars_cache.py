"""tests/test_stars_cache.py — /api/stars response cache regression tests

Locks the home-page payload contract: the ~2.8MB build runs off the event
loop (it used to stall /api/health and SSE for 250-750ms), concurrent
misses share one build, an invalidation during a build is never cached,
and unchanged payloads revalidate with ETag/304.
"""

from __future__ import annotations

import asyncio
import threading
import time

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.routers import stars
from backend.routers.auth import require_auth


@pytest.fixture(autouse=True)
def _reset_cache():
    stars.invalidate_stars_cache()
    yield
    stars.invalidate_stars_cache()


@pytest.fixture
def client():
    app = FastAPI()
    app.include_router(stars.router)
    app.dependency_overrides[require_auth] = lambda: None
    return TestClient(app)


def test_etag_revalidation_returns_304(client, monkeypatch):
    monkeypatch.setattr(stars, "_build_stars_response", lambda: [{"code": "a", "titles": []}])
    first = client.get("/api/stars")
    assert first.status_code == 200
    assert first.json() == [{"code": "a", "titles": []}]
    etag = first.headers["etag"]
    assert first.headers["cache-control"] == "no-cache"

    again = client.get("/api/stars", headers={"If-None-Match": etag})
    assert again.status_code == 304
    # Caddy's encode handler suffixes the ETag; the digest must still match.
    suffixed = client.get("/api/stars", headers={"If-None-Match": etag[:-1] + '-zstd"'})
    assert suffixed.status_code == 304


def test_invalidation_changes_payload(client, monkeypatch):
    data = [{"code": "a", "titles": []}]
    monkeypatch.setattr(stars, "_build_stars_response", lambda: data)
    etag = client.get("/api/stars").headers["etag"]
    data = [{"code": "b", "titles": []}]
    assert client.get("/api/stars", headers={"If-None-Match": etag}).status_code == 304

    stars.invalidate_stars_cache()
    resp = client.get("/api/stars", headers={"If-None-Match": etag})
    assert resp.status_code == 200
    assert resp.json() == [{"code": "b", "titles": []}]


@pytest.mark.asyncio
async def test_build_runs_off_loop_and_is_single_flight(monkeypatch):
    calls = 0
    loop_thread = threading.get_ident()

    def slow_build():
        nonlocal calls
        calls += 1
        assert threading.get_ident() != loop_thread
        time.sleep(0.2)
        return []

    monkeypatch.setattr(stars, "_build_stars_response", slow_build)
    ticks = 0

    async def ticker():
        nonlocal ticks
        for _ in range(10):
            await asyncio.sleep(0.01)
            ticks += 1

    await asyncio.gather(*(stars._get_stars_payload() for _ in range(5)), ticker())
    assert calls == 1
    assert ticks == 10


@pytest.mark.asyncio
async def test_invalidation_during_build_is_not_cached(monkeypatch):
    def build_then_invalidate():
        stars.invalidate_stars_cache()
        return []

    monkeypatch.setattr(stars, "_build_stars_response", build_then_invalidate)
    await stars._get_stars_payload()
    assert stars._stars_cache["body"] is None
