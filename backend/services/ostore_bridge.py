"""ostore → xstream SSE bridge.

Consumes the ostore daemon's event stream server-side and republishes each
object event on the in-process EventBus, so the /files page rides the one
global `/api/events` connection (cookie auth) instead of opening its own
token-in-URL EventSource against ostore.

    ostore /api/events --(httpx stream, ?since=<last id>)--> OstoreBridge
        object.*      -> files.changed {kind, path, type, size?, from?, mtime}
        stream.reset  -> files.resync  (cursor gap: clients must re-list)

The cursor (`last_id`) makes reconnects exact: ostore replays precisely the
events after it, or answers `stream.reset` when that is impossible.
"""

from __future__ import annotations

import asyncio
import json
import os
from collections.abc import AsyncIterator, Awaitable, Callable
from datetime import datetime
from typing import Any

import httpx

from core.events import publish_event
from core.logger import get_logger

log = get_logger("ostore-bridge")

Publish = Callable[[str, dict[str, Any]], Awaitable[None]]

_KINDS = {
    "object.created": "created",
    "object.updated": "updated",
    "object.deleted": "deleted",
    "object.moved": "moved",
    "object.mkdir": "mkdir",
}
MAX_BACKOFF = 30.0


async def iter_sse(lines: AsyncIterator[str]) -> AsyncIterator[tuple[str, str, str | None]]:
    """Yield `(event, data, id)` frames from raw SSE lines."""
    event, data, ev_id = "message", [], None
    async for line in lines:
        if line == "":
            if data:
                yield event, "\n".join(data), ev_id
            event, data, ev_id = "message", [], None
            continue
        if line.startswith(":"):
            continue
        field, _, value = line.partition(":")
        value = value[1:] if value.startswith(" ") else value
        if field == "event":
            event = value
        elif field == "data":
            data.append(value)
        elif field == "id":
            ev_id = value


def _mtime(ts: str | None) -> float | None:
    if not ts:
        return None
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def translate(event: str, data: str) -> tuple[str, dict[str, Any]] | None:
    """Map one ostore SSE frame to an xstream bus event (None = ignore)."""
    if event == "stream.reset":
        return "files.resync", {}
    kind = _KINDS.get(event)
    if kind is None:
        return None
    try:
        body = json.loads(data)
    except json.JSONDecodeError:
        return None
    if not isinstance(body, dict) or not body.get("path"):
        return None
    out: dict[str, Any] = {
        "kind": kind,
        "path": body["path"],
        "type": body.get("type", "file"),
        "mtime": _mtime(body.get("ts")),
    }
    if body.get("size") is not None:
        out["size"] = body["size"]
    if body.get("from"):
        out["from"] = body["from"]
    return "files.changed", out


class OstoreBridge:
    def __init__(self, base_url: str, token: str, publish: Publish = publish_event) -> None:
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.publish = publish
        self.last_id: int | None = None
        self._task: asyncio.Task | None = None

    async def consume(self, lines: AsyncIterator[str]) -> None:
        async for event, data, ev_id in iter_sse(lines):
            if ev_id and ev_id.isdigit():
                self.last_id = int(ev_id)
            mapped = translate(event, data)
            if mapped is not None:
                await self.publish(*mapped)

    async def run(self) -> None:
        backoff = 1.0
        timeout = httpx.Timeout(10.0, read=None)
        headers = {"Authorization": f"Bearer {self.token}", "Accept": "text/event-stream"}
        async with httpx.AsyncClient(timeout=timeout) as client:
            while True:
                params = {"since": str(self.last_id)} if self.last_id is not None else {"replay": "0"}
                had_cursor = self.last_id is not None
                try:
                    async with client.stream("GET", f"{self.base_url}/api/events", params=params, headers=headers) as resp:
                        resp.raise_for_status()
                        log.info(f"connected to ostore events ({'since ' + str(self.last_id) if had_cursor else 'live'})")
                        backoff = 1.0
                        if not had_cursor:
                            # No cursor: whatever happened before this connect is unknown.
                            await self.publish("files.resync", {})
                        await self.consume(resp.aiter_lines())
                    log.warning("ostore event stream ended, reconnecting")
                except asyncio.CancelledError:
                    raise
                except Exception as e:
                    log.warning(f"ostore event stream error: {type(e).__name__}: {e}; retry in {backoff:.0f}s")
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, MAX_BACKOFF)

    def start(self) -> None:
        if self._task is None:
            self._task = asyncio.create_task(self.run(), name="ostore-bridge")

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None


def from_env() -> OstoreBridge | None:
    token = os.environ.get("OSTORE_TOKEN")
    if not token:
        return None
    return OstoreBridge(os.environ.get("OSTORE_INTERNAL_URL", "http://127.0.0.1:8781"), token)
