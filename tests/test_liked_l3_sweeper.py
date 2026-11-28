from __future__ import annotations

from typing import Any

import pytest

from backend.services import bt_client


class _FakeResponse:
    def __init__(self, status_code: int, payload: dict[str, Any]) -> None:
        self.status_code = status_code
        self._payload = payload

    def json(self) -> dict[str, Any]:
        return self._payload


class _FakeAsyncClient:
    def __init__(
        self,
        nodes_payload: dict[str, Any],
        check_sources: dict[str, str],
        local_l1_hashes: set[str] | None = None,
    ) -> None:
        self._nodes_payload = nodes_payload
        self._check_sources = check_sources
        self._local_l1_hashes = set(local_l1_hashes or ())
        self.posted: list[dict[str, Any]] = []
        self.deleted: list[str] = []

    async def get(self, url: str, **_kwargs: Any) -> _FakeResponse:
        if url.endswith("/mesh/nodes"):
            return _FakeResponse(200, self._nodes_payload)
        if "/api/check/" in url:
            h = url.rsplit("/", 1)[-1]
            src = self._check_sources.get(h, "none")
            return _FakeResponse(200, {"source": src, "ready": src == "ostore"})
        if "/torrent/status/" in url:
            h = url.rsplit("/", 1)[-1]
            return _FakeResponse(200 if h in self._local_l1_hashes else 404, {"hash": h})
        return _FakeResponse(404, {})

    async def post(self, url: str, json: dict[str, Any], **_kwargs: Any) -> _FakeResponse:
        self.posted.append({"url": url, "json": json})
        return _FakeResponse(200, {"ok": True})

    async def delete(self, url: str, **_kwargs: Any) -> _FakeResponse:
        self.deleted.append(url)
        return _FakeResponse(200, {"ok": True})


@pytest.mark.asyncio
async def test_liked_l3_sweeper_skips_archived_and_dispatches_one(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("XSTREAM_OMESH_URL", "http://127.0.0.1:8767")
    monkeypatch.setenv("XSTREAM_BT_URL", "http://127.0.0.1:8766")
    monkeypatch.setattr(bt_client, "_archived_submitted", set())
    monkeypatch.setattr(bt_client, "_watchers", {})

    fake = _FakeAsyncClient(
        nodes_payload={
            "node_id": "cc",
            "peers": [
                {
                    "id": "rn",
                    "healthy": True,
                    "bt_enabled": True,
                    "active_jobs": 1,
                    "free_disk_bytes": 30 * 1024**3,
                }
            ],
        },
        check_sources={
            "aaaa" * 10: "ostore",
            "bbbb" * 10: "none",
            "cccc" * 10: "none",
        },
        local_l1_hashes={"aaaa" * 10},
    )
    monkeypatch.setattr(bt_client, "_get_client", lambda: fake)

    rows = [
        ("magnet:?xt=urn:btih:" + "aaaa" * 10, "aaaa" * 10),
        ("magnet:?xt=urn:btih:" + "bbbb" * 10, "bbbb" * 10),
        ("magnet:?xt=urn:btih:" + "cccc" * 10, "cccc" * 10),
    ]
    dispatched = await bt_client.run_liked_l3_sweep_once(lambda: rows)
    assert dispatched == "bbbb" * 10
    assert len(fake.posted) == 1
    assert fake.posted[0]["json"]["kind"] == "bt_archive"
    assert fake.posted[0]["json"]["hash"] == "bbbb" * 10
    assert ("aaaa" * 10) in bt_client._archived_submitted
    assert any(u.endswith(f"/api/cache/pin/{'aaaa' * 10}") for u in fake.deleted)
    assert any(u.endswith(f"/api/cache/{'aaaa' * 10}") for u in fake.deleted)


@pytest.mark.asyncio
async def test_liked_l3_sweeper_waits_when_peers_busy(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("XSTREAM_OMESH_URL", "http://127.0.0.1:8767")
    monkeypatch.setattr(bt_client, "_archived_submitted", set())
    monkeypatch.setattr(bt_client, "_watchers", {})

    fake = _FakeAsyncClient(
        nodes_payload={
            "node_id": "cc",
            "peers": [
                {
                    "id": "rn",
                    "healthy": True,
                    "bt_enabled": True,
                    "active_jobs": 3,
                    "free_disk_bytes": 30 * 1024**3,
                }
            ],
        },
        check_sources={},
    )
    monkeypatch.setattr(bt_client, "_get_client", lambda: fake)

    dispatched = await bt_client.run_liked_l3_sweep_once(
        lambda: [("magnet:?xt=urn:btih:" + "dddd" * 10, "dddd" * 10)]
    )
    assert dispatched is None
    assert fake.posted == []
