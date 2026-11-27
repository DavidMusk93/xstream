"""Locks bt_client SSE event awaiting and disconnect-aware Range streaming."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock

import httpx
import pytest

from backend.services import bt_client


@pytest.mark.asyncio
async def test_watch_hash_awaits_eventbus_publish(monkeypatch):
    """Regression: bt_client previously forgot `await` on EventBus.publish()."""
    monkeypatch.setenv("XSTREAM_BT_URL", "http://127.0.0.1:8766")

    published: list[tuple[str, dict]] = []

    class FakeBus:
        async def publish(self, event: str, data: dict) -> None:
            published.append((event, data))

    monkeypatch.setattr(bt_client, "get_bus", lambda: FakeBus())

    responses = [
        {"hash": "a" * 40, "state": "downloading", "head_ready": False, "progress": 0.5},
        {"hash": "a" * 40, "state": "finished", "head_ready": True, "ready": True, "progress": 100.0},
    ]
    call_idx = {"i": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        idx = min(call_idx["i"], len(responses) - 1)
        call_idx["i"] += 1
        return httpx.Response(200, json=responses[idx])

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    monkeypatch.setattr(bt_client, "_get_client", lambda: client)

    real_sleep = asyncio.sleep

    async def fast_sleep(_sec: float) -> None:
        await real_sleep(0)

    monkeypatch.setattr(asyncio, "sleep", fast_sleep)

    h = "a" * 40
    bt_client._watch_hash(h)
    task = bt_client._watchers[h]
    await asyncio.wait_for(task, timeout=2.0)
    await client.aclose()

    event_names = [e for e, _ in published]
    assert "torrent.progress" in event_names
    assert "torrent.head_ready" in event_names
    assert "torrent.status" in event_names


@pytest.mark.asyncio
async def test_stream_video_aborts_on_client_disconnect(monkeypatch):
    """When browser cancels an old Range request, bt_client returns 499 instead of hanging."""
    monkeypatch.setenv("XSTREAM_BT_URL", "http://127.0.0.1:8766")

    class FakeRequest:
        headers = {"Range": "bytes=1048576-"}

        async def is_disconnected(self) -> bool:
            return True

    class HangingClient:
        def build_request(self, method: str, url: str, headers: dict | None = None):
            return httpx.Request(method, url, headers=headers)

        async def send(self, req, stream: bool = False):
            await asyncio.sleep(60)
            raise AssertionError("should have been cancelled")

    monkeypatch.setattr(bt_client, "_get_client", lambda: HangingClient())
    resp = await asyncio.wait_for(bt_client.stream_video(FakeRequest(), "b" * 40), timeout=2.0)
    assert resp.status_code == 499


@pytest.mark.asyncio
async def test_progress_broadcaster_publishes_active_downloads_when_sse_connected(monkeypatch):
    """Background downloads restored by xstream_bt still emit torrent.progress to CachePanel."""
    monkeypatch.setenv("XSTREAM_BT_URL", "http://127.0.0.1:8766")

    published: list[tuple[str, dict]] = []
    done_ev = asyncio.Event()

    class FakeBus:
        def subscriber_count(self) -> int:
            return 1

        async def publish(self, event: str, data: dict) -> None:
            published.append((event, data))
            done_ev.set()

    monkeypatch.setattr(bt_client, "get_bus", lambda: FakeBus())

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "totalSize": 1000,
                "maxSize": 2000,
                "itemCount": 1,
                "items": [{
                    "hash": "c" * 40,
                    "state": "downloading",
                    "progress": 12.5,
                    "local_size": 1000,
                    "piece_segments": [[0.0, 50.0, 2], [50.0, 100.0, 0]],
                    "pinned": True,
                }],
            },
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    monkeypatch.setattr(bt_client, "_get_client", lambda: client)

    real_sleep = asyncio.sleep

    async def fast_sleep(_sec: float) -> None:
        await real_sleep(0)

    monkeypatch.setattr(asyncio, "sleep", fast_sleep)

    bt_client.start_progress_broadcaster()
    await asyncio.wait_for(done_ev.wait(), timeout=2.0)
    await bt_client.close_client()
    await client.aclose()

    assert any(e == "torrent.progress" and d.get("hash") == "c" * 40 for e, d in published)


@pytest.mark.asyncio
async def test_delete_star_clears_xstream_bt_cache_and_pins(monkeypatch, tmp_path):
    """Regression: delete_star must unpin and delete cached torrents via xstream_bt."""
    import json
    from fastapi import HTTPException
    from types import SimpleNamespace
    from backend.routers import stars as stars_router

    monkeypatch.setenv("XSTREAM_BT_URL", "http://127.0.0.1:8766")

    cfg_path = tmp_path / "config.json"
    cfg_path.write_text(json.dumps({"stars": [{"code": "TST-001", "name": "Test Star"}]}))
    monkeypatch.setattr(stars_router, "CONFIG_PATH", str(cfg_path))
    monkeypatch.setattr(stars_router, "invalidate_stars_cache", lambda: None)

    h_cached = "d" * 40
    h_missing = "e" * 40

    async def fake_db_read(fn, *args, **kwargs):
        return [h_cached, h_missing]

    async def fake_db_write(fn, *args, **kwargs):
        return True

    monkeypatch.setattr(stars_router, "db_read", fake_db_read)
    monkeypatch.setattr(stars_router, "db_write", fake_db_write)

    unpinned: list[tuple[str, bool]] = []
    deleted: list[str] = []

    async def fake_set_pin(h: str, *, pinned: bool) -> None:
        unpinned.append((h, pinned))

    async def fake_cache_delete(h: str) -> dict:
        deleted.append(h)
        if h == h_missing:
            raise HTTPException(status_code=404, detail="Torrent not found")
        return {"deleted": True}

    monkeypatch.setattr(bt_client, "set_pin", fake_set_pin)
    monkeypatch.setattr(bt_client, "cache_delete", fake_cache_delete)

    fake_req = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(engine=SimpleNamespace())))
    result = await stars_router.delete_star(fake_req, code="TST-001")

    assert result == {"code": "TST-001", "deleted": True}
    assert unpinned == [(h_cached, False), (h_missing, False)]
    assert deleted == [h_cached, h_missing]


@pytest.mark.asyncio
async def test_check_stream_prefers_omesh_and_falls_back_to_bt(monkeypatch):
    """When XSTREAM_OMESH_URL is set, check_stream queries omesh first and falls back to xstream_bt."""
    monkeypatch.setenv("XSTREAM_BT_URL", "http://127.0.0.1:8766")
    monkeypatch.setenv("XSTREAM_OMESH_URL", "http://127.0.0.1:8767")

    seen: list[str] = []

    def handler_ok(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        return httpx.Response(200, json={"hash": "f" * 40, "head_ready": True, "source": "ostore"})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler_ok))
    monkeypatch.setattr(bt_client, "_get_client", lambda: client)

    resp = await bt_client.check_stream("f" * 40)
    await client.aclose()
    assert resp.status_code == 200
    assert seen == [f"http://127.0.0.1:8767/api/check/{'f' * 40}"]

    # Now simulate omesh down -> automatic fallback to xstream_bt
    seen_fb: list[str] = []

    def handler_fb(request: httpx.Request) -> httpx.Response:
        seen_fb.append(str(request.url))
        if ":8767" in str(request.url):
            raise httpx.ConnectError("omesh offline", request=request)
        return httpx.Response(200, json={"hash": "f" * 40, "head_ready": False})

    client2 = httpx.AsyncClient(transport=httpx.MockTransport(handler_fb))
    monkeypatch.setattr(bt_client, "_get_client", lambda: client2)

    resp2 = await bt_client.check_stream("f" * 40)
    await client2.aclose()
    assert resp2.status_code == 200
    assert len(seen_fb) == 2
    assert seen_fb[0].startswith("http://127.0.0.1:8767/")
    assert seen_fb[1].startswith("http://127.0.0.1:8766/")



