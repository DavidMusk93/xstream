"""tests/test_add_star.py — POST /api/stars/add URL parsing regression tests

Locks the tolerant actress-URL contract: the site links actress pages with
a trailing slash, users paste scheme-less / `www.` / uppercase / query-string
forms, and pasting the same performer twice must 409 instead of creating a
duplicate star (dedupe is by actress id, not by URL string).
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.routers import stars as stars_router
from backend.routers.auth import require_auth
from scrapers.v2.extractors import normalize_actress_url

_STAR_PAGE = (
    "<html><body><h1>Julia</h1>"
    '<div class="video-item">'
    '<a href="/movie/julia-001-999"><img alt="JULIA-001 title"/></a>'
    '<div class="mb-2">Released 01/15/2026</div>'
    '<div class="mb-1"><a href="/actress/julia-326">Julia</a></div><table>'
    '<tr><td><a href="magnet:?xt=urn:btih:' + "a" * 40 + '&dn=JULIA-001">dl</a>'
    '<i class="fa-weight-hanging"></i> 5.2 GB <strong>S:</strong> 10</td></tr>'
    "</table></div></body></html>"
)

_CONFIG = {"stars": []}


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("https://ijavtorrent.com/actress/julia-326", "https://ijavtorrent.com/actress/julia-326"),
        ("https://ijavtorrent.com/actress/julia-326/", "https://ijavtorrent.com/actress/julia-326"),
        ("https://ijavtorrent.com/actress/julia-326///", "https://ijavtorrent.com/actress/julia-326"),
        ("http://ijavtorrent.com/actress/julia-326/", "https://ijavtorrent.com/actress/julia-326"),
        ("ijavtorrent.com/actress/julia-326/", "https://ijavtorrent.com/actress/julia-326"),
        ("www.ijavtorrent.com/actress/julia-326/", "https://ijavtorrent.com/actress/julia-326"),
        ("https://ijavtorrent.com/actress/JULIA-326/", "https://ijavtorrent.com/actress/julia-326"),
        ("https://ijavtorrent.com/actress/julia-326/?page=2", "https://ijavtorrent.com/actress/julia-326"),
        ("https://ijavtorrent.com/actress/julia-326#top", "https://ijavtorrent.com/actress/julia-326"),
        ("  https://ijavtorrent.com/actress/229scute-1575/  ", "https://ijavtorrent.com/actress/229scute-1575"),
        ("<https://ijavtorrent.com/actress/julia-326/>", "https://ijavtorrent.com/actress/julia-326"),
    ],
)
def test_normalize_actress_url_accepts_site_forms(raw, expected):
    parsed = normalize_actress_url(raw)
    assert parsed is not None
    assert parsed[0] == expected


@pytest.mark.parametrize(
    "raw",
    [
        "",
        "julia-326",
        "https://ijavtorrent.com/actresses?searchTerm=julia",
        "https://ijavtorrent.com/movie/julia-001-999",
        "https://evil.com/actress/julia-326",
        "https://ijavtorrent.com.evil.com/actress/julia-326",
    ],
)
def test_normalize_actress_url_rejects_non_actress_pages(raw):
    assert normalize_actress_url(raw) is None


@pytest.fixture
def client(monkeypatch, tmp_path):
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps(_CONFIG))
    monkeypatch.setattr(stars_router, "CONFIG_PATH", str(config_path))
    monkeypatch.setattr(
        "scrapers.v2.fetchers.HttpxFetcher.fetch",
        AsyncMock(return_value=_STAR_PAGE),
    )
    monkeypatch.setattr(stars_router, "db_write", AsyncMock())
    monkeypatch.setattr(stars_router, "publish_event", AsyncMock())
    monkeypatch.setattr(stars_router, "invalidate_stars_cache", lambda: None)
    monkeypatch.setattr(
        "scrapers.v2.tasks.sync_titles.sync_star",
        AsyncMock(return_value={"count": 0}),
    )

    app = FastAPI()
    app.dependency_overrides[require_auth] = lambda: None
    app.include_router(stars_router.router)
    return TestClient(app), config_path


def test_add_star_accepts_trailing_slash(client):
    http, config_path = client
    res = http.post(
        "/api/stars/add",
        json={"star_page_url": "https://ijavtorrent.com/actress/julia-326/"},
    )
    assert res.status_code == 200
    body = res.json()
    assert body["star_page_url"] == "https://ijavtorrent.com/actress/julia-326"
    assert body["handle"] == "julia"
    saved = json.loads(config_path.read_text())["stars"]
    assert [s["star_page_url"] for s in saved] == ["https://ijavtorrent.com/actress/julia-326"]


def test_add_star_dedupes_by_actress_id(client):
    http, _ = client
    first = http.post(
        "/api/stars/add",
        json={"star_page_url": "https://ijavtorrent.com/actress/julia-326/"},
    )
    assert first.status_code == 200
    # Same performer, different URL spelling — must not create a duplicate
    for dup in (
        "https://ijavtorrent.com/actress/julia-326",
        "http://ijavtorrent.com/actress/julia-326/",
        "ijavtorrent.com/actress/julia-326/?page=2",
    ):
        res = http.post("/api/stars/add", json={"star_page_url": dup})
        assert res.status_code == 409, dup


def test_add_star_rejects_non_actress_url(client):
    http, _ = client
    res = http.post(
        "/api/stars/add",
        json={"star_page_url": "https://ijavtorrent.com/actresses?searchTerm=julia"},
    )
    assert res.status_code == 400
    assert "actress" in res.json()["detail"]
