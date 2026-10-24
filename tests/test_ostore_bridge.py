"""Locks the ostore → SSE bridge (backend/services/ostore_bridge.py).

- ostore object.* frames become `files.changed` with kind/path/type/size/from/mtime
- `stream.reset` becomes `files.resync`; unknown frames and pings are ignored
- the event id cursor advances, and reconnects resume with `?since=<id>`
  (first connect is live-only `replay=0` + a `files.resync`)
"""

from __future__ import annotations

import asyncio
from typing import Any

import httpx
import pytest

from backend.services import ostore_bridge
from backend.services.ostore_bridge import OstoreBridge, translate


async def _lines(text: str):
    for line in text.split("\n"):
        yield line


def test_translate_maps_object_events():
    name, data = translate(
        "object.moved",
        '{"id":7,"path":"a/b.mp4","type":"file","size":3,"from":"b.mp4","ts":"2026-10-24T06:00:00Z"}',
    )
    assert name == "files.changed"
    assert data["kind"] == "moved"
    assert data["path"] == "a/b.mp4"
    assert data["from"] == "b.mp4"
    assert data["size"] == 3
    assert data["type"] == "file"
    assert data["mtime"] == pytest.approx(1792821600.0)


def test_translate_reset_and_unknown():
    assert translate("stream.reset", '{"reason":"cursor"}') == ("files.resync", {})
    assert translate("message", "ping") is None
    assert translate("object.created", "not json") is None


def test_consume_publishes_and_tracks_cursor():
    got: list[tuple[str, dict[str, Any]]] = []

    async def publish(event: str, data: dict[str, Any]) -> None:
        got.append((event, data))

    stream = (
        ":ping\n\n"
        'id: 41\nevent: object.mkdir\ndata: {"id":41,"path":"d","type":"dir","ts":"2026-10-24T06:00:00Z"}\n\n'
        'id: 42\nevent: object.deleted\ndata: {"id":42,"path":"d/x","type":"file","ts":"2026-10-24T06:00:01Z"}\n\n'
        'event: stream.reset\ndata: {"reason":"lagged"}\n\n'
    )
    bridge = OstoreBridge("http://ostore", "t", publish)
    asyncio.run(bridge.consume(_lines(stream)))
    assert [e for e, _ in got] == ["files.changed", "files.changed", "files.resync"]
    assert got[0][1]["kind"] == "mkdir" and got[0][1]["type"] == "dir"
    assert got[1][1]["kind"] == "deleted"
    assert bridge.last_id == 42


def test_reconnect_resumes_with_since(monkeypatch):
    seen: list[dict[str, str]] = []
    got: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(dict(request.url.params))
        assert request.headers["authorization"] == "Bearer tok"
        body = 'id: 9\nevent: object.created\ndata: {"id":9,"path":"v.mp4","type":"file","size":1}\n\n'
        return httpx.Response(200, text=body, headers={"content-type": "text/event-stream"})

    real_client = httpx.AsyncClient
    monkeypatch.setattr(
        ostore_bridge.httpx,
        "AsyncClient",
        lambda **kw: real_client(transport=httpx.MockTransport(handler), **kw),
    )

    async def publish(event: str, data: dict[str, Any]) -> None:
        got.append(event)

    async def no_sleep(_s: float) -> None:
        if len(seen) >= 2:
            raise asyncio.CancelledError

    monkeypatch.setattr(ostore_bridge.asyncio, "sleep", no_sleep)
    bridge = OstoreBridge("http://ostore/", "tok", publish)
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(bridge.run())
    assert seen[0] == {"replay": "0"}
    assert seen[1] == {"since": "9"}
    assert got == ["files.resync", "files.changed", "files.changed"]
