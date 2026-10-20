"""tests/test_x_media.py — Local cache for injected X (twimg) images

Locks the media-proxy contract: cache keys/filenames are stable and
whitelist-shaped; only https://pbs.twimg.com is ever fetched (no open
proxy); downloads enforce image content-type and a size cap and land
atomically in images/x/; GET /api/social/x/media/{filename} 307-redirects
on a disk hit, fetches+caches on a miss, and rejects bad names/sources.
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.services import x_media

MEDIA_URL = "https://pbs.twimg.com/media/GZabc?format=jpg&name=small"
AVATAR_URL = "https://pbs.twimg.com/profile_images/123/abc_bigger.jpg"
PNG_URL = "https://pbs.twimg.com/media/XYZ?format=png&name=small"

JPEG_BYTES = b"\xff\xd8\xff" + b"\x00" * 128


@pytest.fixture
def media_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(x_media, "MEDIA_DIR", tmp_path / "x")
    return x_media.MEDIA_DIR


# ── Keys, filenames, URLs ───────────────────────────────────────────

def test_cache_key_and_filename_are_stable():
    assert x_media.cache_key(MEDIA_URL) == x_media.cache_key(MEDIA_URL)
    assert len(x_media.cache_key(MEDIA_URL)) == 24
    assert x_media.filename_for(MEDIA_URL).endswith(".jpg")
    assert x_media.filename_for(PNG_URL).endswith(".png")
    # Video thumbs carry no format param: the path suffix wins.
    thumb = "https://pbs.twimg.com/ext_tw_video_thumb/1/pu/img/x.jpg"
    assert x_media.filename_for(thumb).endswith(".jpg")


def test_validate_source_only_allows_twimg_https():
    assert x_media.validate_source(MEDIA_URL)
    assert x_media.validate_source(AVATAR_URL)
    assert not x_media.validate_source("http://pbs.twimg.com/media/A.jpg")
    assert not x_media.validate_source("https://evil.com/media/A.jpg")
    assert not x_media.validate_source("https://pbs.twimg.com.evil.com/media/A.jpg")
    assert not x_media.validate_source("not a url")


def test_proxy_url_rewrites_twimg_and_passes_through_the_rest():
    proxied = x_media.proxy_url(MEDIA_URL)
    assert proxied.startswith("/api/social/x/media/")
    assert x_media.valid_filename(proxied.split("?")[0].rsplit("/", 1)[-1])
    from urllib.parse import parse_qs, urlsplit
    u = parse_qs(urlsplit(proxied).query)["u"][0]
    assert u == MEDIA_URL  # original stays recoverable for client fallback
    assert x_media.proxy_url("https://evil.com/x.jpg") == "https://evil.com/x.jpg"


# ── Download into the cache ─────────────────────────────────────────

def _mock_client(monkeypatch, handler):
    import httpx

    real_client = httpx.AsyncClient

    def factory(*args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(handler)
        return real_client(*args, **kwargs)

    monkeypatch.setattr(x_media.httpx, "AsyncClient", factory)


@pytest.mark.asyncio
async def test_fetch_to_cache_writes_file(media_dir, monkeypatch):
    import httpx

    def handler(request):
        return httpx.Response(200, content=JPEG_BYTES, headers={"content-type": "image/jpeg"})

    _mock_client(monkeypatch, handler)
    path = await x_media.fetch_to_cache(MEDIA_URL)
    assert path == media_dir / x_media.filename_for(MEDIA_URL)
    assert path.read_bytes() == JPEG_BYTES
    # Second call is a disk hit — the handler must not run again.
    def boom(request):
        raise AssertionError("network hit on a cached file")

    _mock_client(monkeypatch, boom)
    assert await x_media.fetch_to_cache(MEDIA_URL) == path


@pytest.mark.asyncio
async def test_fetch_to_cache_rejects_bad_responses(media_dir, monkeypatch):
    import httpx

    _mock_client(monkeypatch, lambda req: httpx.Response(404))
    assert await x_media.fetch_to_cache(MEDIA_URL) is None

    _mock_client(monkeypatch, lambda req: httpx.Response(
        200, content=b"<html></html>", headers={"content-type": "text/html"}))
    assert await x_media.fetch_to_cache(MEDIA_URL) is None

    monkeypatch.setattr(x_media, "MAX_BYTES", 8)
    _mock_client(monkeypatch, lambda req: httpx.Response(
        200, content=JPEG_BYTES, headers={"content-type": "image/jpeg"}))
    assert await x_media.fetch_to_cache(MEDIA_URL) is None
    assert not list(media_dir.iterdir())  # no partial files left behind


@pytest.mark.asyncio
async def test_fetch_to_cache_rejects_non_twimg_without_network(media_dir):
    assert await x_media.fetch_to_cache("https://evil.com/x.jpg") is None


@pytest.mark.asyncio
async def test_warm_is_best_effort(media_dir, monkeypatch):
    import httpx

    def handler(request):
        if "GZabc" in str(request.url):
            return httpx.Response(200, content=JPEG_BYTES, headers={"content-type": "image/jpeg"})
        return httpx.Response(500)

    _mock_client(monkeypatch, handler)
    await x_media.warm([MEDIA_URL, PNG_URL, None, "https://evil.com/x.jpg"])
    assert (media_dir / x_media.filename_for(MEDIA_URL)).is_file()
    assert not (media_dir / x_media.filename_for(PNG_URL)).exists()


# ── Route ───────────────────────────────────────────────────────────

@pytest.fixture
def client(media_dir):
    from backend.routers import social
    from backend.routers.auth import require_auth

    app = FastAPI()
    app.include_router(social.router)
    app.dependency_overrides[require_auth] = lambda: None
    return TestClient(app)


def test_media_route_rejects_bad_names_and_sources(client):
    assert client.get("/api/social/x/media/not-a-key.jpg").status_code == 404
    filename = x_media.filename_for(MEDIA_URL)
    assert client.get(f"/api/social/x/media/{filename}").status_code == 400
    assert client.get(
        f"/api/social/x/media/{filename}", params={"u": "https://evil.com/x.jpg"}
    ).status_code == 400


def test_media_route_redirects_on_disk_hit(client, media_dir):
    media_dir.mkdir(parents=True)
    filename = x_media.filename_for(MEDIA_URL)
    (media_dir / filename).write_bytes(JPEG_BYTES)
    r = client.get(f"/api/social/x/media/{filename}", follow_redirects=False)
    assert r.status_code == 307
    assert r.headers["location"] == f"/images/x/{filename}"
    assert "immutable" in r.headers["cache-control"]


def test_media_route_fetches_and_caches_on_miss(client, media_dir, monkeypatch):
    import httpx

    def handler(request):
        return httpx.Response(200, content=JPEG_BYTES, headers={"content-type": "image/jpeg"})

    _mock_client(monkeypatch, handler)
    filename = x_media.filename_for(MEDIA_URL)
    r = client.get(f"/api/social/x/media/{filename}", params={"u": MEDIA_URL})
    assert r.status_code == 200
    assert r.content == JPEG_BYTES
    assert r.headers["content-type"] == "image/jpeg"
    assert (media_dir / filename).is_file()  # next request is a static redirect


def test_media_route_502_when_fetch_fails(client, media_dir, monkeypatch):
    import httpx

    _mock_client(monkeypatch, lambda req: httpx.Response(404))
    filename = x_media.filename_for(MEDIA_URL)
    r = client.get(f"/api/social/x/media/{filename}", params={"u": MEDIA_URL})
    assert r.status_code == 502
