from __future__ import annotations

import asyncio
import os
from typing import Any

import httpx
from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse, Response, StreamingResponse

from core import get_logger
from core.events import get_bus

log = get_logger("bt-client")

_client: httpx.AsyncClient | None = None
_watchers: dict[str, asyncio.Task[None]] = {}
_broadcaster_task: asyncio.Task[None] | None = None


def get_base_url() -> str | None:
    """Return configured xstream_bt base URL (e.g. http://127.0.0.1:8766), or None if disabled."""
    raw = os.environ.get("XSTREAM_BT_URL", "").strip().rstrip("/")
    return raw or None


def get_omesh_url() -> str | None:
    """Return configured omesh CDN/edge URL (e.g. http://127.0.0.1:8767), or None if disabled."""
    raw = os.environ.get("XSTREAM_OMESH_URL", "").strip().rstrip("/")
    return raw or None


def is_enabled() -> bool:
    """Return True when the Rust xstream_bt daemon is enabled via XSTREAM_BT_URL."""
    return get_base_url() is not None


def _get_client() -> httpx.AsyncClient:
    global _client
    if _client is None or _client.is_closed:
        # Streaming Range requests may wait for remote BitTorrent peers to deliver
        # requested pieces, so use a generous read timeout while keeping connect fast.
        _client = httpx.AsyncClient(
            timeout=httpx.Timeout(connect=5.0, read=120.0, write=10.0, pool=10.0),
            limits=httpx.Limits(max_connections=64, max_keepalive_connections=16),
        )
    return _client


async def close_client() -> None:
    """Shut down background watchers, broadcaster, and close the shared HTTP client."""
    global _broadcaster_task, _client
    if _broadcaster_task is not None and not _broadcaster_task.done():
        _broadcaster_task.cancel()
        try:
            await _broadcaster_task
        except asyncio.CancelledError:
            pass
    _broadcaster_task = None
    for task in list(_watchers.values()):
        task.cancel()
    _watchers.clear()
    if _client is not None and not _client.is_closed:
        await _client.aclose()
    _client = None


def start_progress_broadcaster() -> None:
    """Broadcast live torrent.progress for all active xstream_bt downloads while SSE clients exist."""
    global _broadcaster_task
    if not is_enabled():
        return
    if _broadcaster_task is not None and not _broadcaster_task.done():
        return

    async def _loop() -> None:
        last_states: dict[str, str] = {}
        try:
            while True:
                await asyncio.sleep(2.0)
                bus = get_bus()
                if bus.subscriber_count() <= 0:
                    continue
                base = get_base_url()
                if not base:
                    continue
                try:
                    resp = await _get_client().get(f"{base}/api/cache", timeout=5.0)
                except Exception:
                    continue
                if resp.status_code != 200:
                    continue
                items = resp.json().get("items") or []
                for item in items:
                    h = str(item.get("hash") or "").lower()
                    if not h:
                        continue
                    state = str(item.get("state") or "")
                    prev = last_states.get(h)
                    last_states[h] = state
                    # Avoid duplicating hashes already watched by per-hash _watch_hash
                    if h in _watchers:
                        continue
                    if state == "downloading" or (prev == "downloading" and state != prev):
                        await bus.publish("torrent.progress", item)
        except asyncio.CancelledError:
            pass

    try:
        _broadcaster_task = asyncio.create_task(_loop(), name="bt-progress-broadcaster")
    except RuntimeError:
        pass


def _watch_hash(hash_str: str) -> None:
    """Start a lightweight SSE status publisher for an active torrent hash."""
    h = hash_str.lower()
    existing = _watchers.get(h)
    if existing is not None and not existing.done():
        return

    async def _run() -> None:
        base = get_base_url()
        if not base:
            return
        head_emitted = False
        consecutive_errors = 0
        try:
            while True:
                await asyncio.sleep(1.0 if not head_emitted else 1.5)
                try:
                    resp = await _get_client().get(f"{base}/torrent/status/{h}", timeout=5.0)
                    consecutive_errors = 0
                except Exception:
                    consecutive_errors += 1
                    if consecutive_errors >= 15:
                        break
                    continue
                if resp.status_code != 200:
                    break
                data = resp.json()
                bus = get_bus()
                await bus.publish("torrent.progress", data)
                if data.get("head_ready") and not head_emitted:
                    head_emitted = True
                    await bus.publish("torrent.head_ready", {"hash": h})
                state = data.get("state")
                if state in ("paused", "finished", "error"):
                    await bus.publish(
                        "torrent.status",
                        {"hash": h, "state": state, "ready": data.get("ready", False)},
                    )
                    break
        except asyncio.CancelledError:
            pass
        finally:
            _watchers.pop(h, None)

    try:
        _watchers[h] = asyncio.create_task(_run(), name=f"bt-watch:{h[:12]}")
    except RuntimeError:
        pass


def _stop_watch(hash_str: str) -> None:
    task = _watchers.pop(hash_str.lower(), None)
    if task is not None and not task.done():
        task.cancel()


async def add_torrent(magnet: str, *, prefetch: bool = False) -> dict[str, Any]:
    """Forward POST /torrent/add to xstream_bt and start SSE progress watch."""
    base = get_base_url()
    assert base is not None
    try:
        resp = await _get_client().post(
            f"{base}/torrent/add",
            json={"magnet": magnet, "prefetch": prefetch},
            timeout=15.0,
        )
    except httpx.HTTPError as exc:
        log.error(f"xstream_bt add_torrent failed: {exc}")
        raise HTTPException(status_code=503, detail="BitTorrent daemon unavailable")
    if resp.status_code >= 400:
        detail = resp.json().get("detail", "add_torrent failed") if resp.headers.get("content-type", "").startswith("application/json") else resp.text
        raise HTTPException(status_code=resp.status_code, detail=detail)
    data = resp.json()
    if not prefetch and data.get("hash"):
        _watch_hash(data["hash"])
        if data.get("ready"):
            # Only emit head_ready immediately if the torrent already has head data;
            # otherwise the watcher emits it as soon as xstream_bt reports head_ready.
            try:
                st = await get_status(data["hash"])
                if st.get("head_ready"):
                    await get_bus().publish("torrent.head_ready", {"hash": data["hash"]})
            except Exception:
                pass
    return data


async def get_status(hash_str: str) -> dict[str, Any]:
    """Forward GET /torrent/status/{hash} to xstream_bt."""
    base = get_base_url()
    assert base is not None
    try:
        resp = await _get_client().get(f"{base}/torrent/status/{hash_str}", timeout=5.0)
    except httpx.HTTPError as exc:
        log.error(f"xstream_bt status failed: {exc}")
        raise HTTPException(status_code=503, detail="BitTorrent daemon unavailable")
    if resp.status_code == 404:
        raise HTTPException(status_code=404, detail="Not found")
    if resp.status_code >= 400:
        raise HTTPException(status_code=resp.status_code, detail=resp.text)
    return resp.json()


async def check_stream(hash_str: str) -> JSONResponse:
    """Forward GET /api/check/{hash} to omesh (if enabled) with automatic xstream_bt fallback."""
    omesh = get_omesh_url()
    if omesh:
        try:
            resp = await _get_client().get(f"{omesh}/api/check/{hash_str}", timeout=3.0)
            if resp.status_code == 200:
                return JSONResponse(
                    content=resp.json(),
                    headers={"Cache-Control": "no-store, no-cache, must-revalidate, max-age=0"},
                )
        except httpx.HTTPError as exc:
            log.debug(f"omesh check fallback to xstream_bt: {exc}")

    base = get_base_url()
    assert base is not None
    try:
        resp = await _get_client().get(f"{base}/api/check/{hash_str}", timeout=5.0)
    except httpx.HTTPError as exc:
        log.error(f"xstream_bt check failed: {exc}")
        raise HTTPException(status_code=503, detail="BitTorrent daemon unavailable")
    if resp.status_code >= 400:
        raise HTTPException(status_code=resp.status_code, detail=resp.text)
    return JSONResponse(
        content=resp.json(),
        headers={"Cache-Control": "no-store, no-cache, must-revalidate, max-age=0"},
    )


async def control_action(action: str, payload: dict[str, Any]) -> dict[str, Any]:
    """Forward /torrent/{pause,resume,seek,progress} to xstream_bt."""
    base = get_base_url()
    assert base is not None
    try:
        resp = await _get_client().post(f"{base}/torrent/{action}", json=payload, timeout=10.0)
    except httpx.HTTPError as exc:
        log.error(f"xstream_bt {action} failed: {exc}")
        raise HTTPException(status_code=503, detail="BitTorrent daemon unavailable")
    if resp.status_code >= 400:
        detail = resp.json().get("detail", f"{action} failed") if resp.headers.get("content-type", "").startswith("application/json") else resp.text
        raise HTTPException(status_code=resp.status_code, detail=detail)
    h = payload.get("hash", "")
    if h:
        if action == "resume":
            _watch_hash(h)
        elif action == "pause":
            _stop_watch(h)
    return resp.json()


async def _wait_disconnect(request: Request) -> None:
    """Resolve as soon as the downstream client disconnects."""
    while True:
        if await request.is_disconnected():
            return
        await asyncio.sleep(0.05)


async def stream_video(request: Request, hash_str: str) -> Response:
    """Stream GET /stream/{hash} directly from xstream_bt without buffering.

    Actively watches downstream client disconnect both while awaiting upstream
    headers and while streaming chunks so fast-scrub Range cancellations drop
    the upstream librqbit FileStream immediately instead of starving new seeks.
    """
    base = get_base_url()
    assert base is not None
    stream_base = get_omesh_url() or base
    req_headers: dict[str, str] = {}
    range_hdr = request.headers.get("Range")
    if range_hdr:
        req_headers["Range"] = range_hdr

    client = _get_client()
    req = client.build_request("GET", f"{stream_base}/stream/{hash_str}", headers=req_headers)

    send_task = asyncio.create_task(client.send(req, stream=True))
    disc_task = asyncio.create_task(_wait_disconnect(request))
    try:
        done, pending = await asyncio.wait(
            {send_task, disc_task},
            return_when=asyncio.FIRST_COMPLETED,
        )
        for p in pending:
            p.cancel()
        if disc_task in done and send_task not in done:
            try:
                await send_task
            except (asyncio.CancelledError, Exception):
                pass
            return Response(status_code=499)
        upstream = send_task.result()
    except httpx.HTTPError as exc:
        if stream_base != base:
            log.warning(f"omesh stream failed ({exc}), falling back to xstream_bt")
            try:
                fallback_req = client.build_request("GET", f"{base}/stream/{hash_str}", headers=req_headers)
                upstream = await client.send(fallback_req, stream=True)
            except httpx.HTTPError as fb_exc:
                log.error(f"xstream_bt stream fallback failed: {fb_exc}")
                raise HTTPException(status_code=503, detail="BitTorrent daemon unavailable")
        else:
            log.error(f"xstream_bt stream failed: {exc}")
            raise HTTPException(status_code=503, detail="BitTorrent daemon unavailable")

    out_headers: dict[str, str] = {}
    for key in ("content-type", "content-length", "content-range", "accept-ranges", "x-omesh-source"):
        val = upstream.headers.get(key)
        if val is not None:
            out_headers[key] = val

    if upstream.status_code >= 400:
        body = await upstream.aread()
        await upstream.aclose()
        return Response(content=body, status_code=upstream.status_code, headers=out_headers)

    async def _iter_chunks():
        try:
            async for chunk in upstream.aiter_bytes(chunk_size=65_536):
                if await request.is_disconnected():
                    break
                yield chunk
        except (asyncio.CancelledError, httpx.HTTPError):
            pass
        finally:
            await upstream.aclose()

    return StreamingResponse(
        _iter_chunks(),
        status_code=upstream.status_code,
        headers=out_headers,
    )


async def cache_list() -> dict[str, Any]:
    """Forward GET /api/cache to xstream_bt."""
    base = get_base_url()
    assert base is not None
    try:
        resp = await _get_client().get(f"{base}/api/cache", timeout=10.0)
    except httpx.HTTPError as exc:
        log.error(f"xstream_bt cache_list failed: {exc}")
        raise HTTPException(status_code=503, detail="BitTorrent daemon unavailable")
    if resp.status_code >= 400:
        raise HTTPException(status_code=resp.status_code, detail=resp.text)
    return resp.json()


async def cache_metrics() -> dict[str, Any]:
    """Forward GET /api/cache/metrics to xstream_bt."""
    base = get_base_url()
    assert base is not None
    try:
        resp = await _get_client().get(f"{base}/api/cache/metrics", timeout=10.0)
    except httpx.HTTPError as exc:
        log.error(f"xstream_bt cache_metrics failed: {exc}")
        raise HTTPException(status_code=503, detail="BitTorrent daemon unavailable")
    if resp.status_code >= 400:
        raise HTTPException(status_code=resp.status_code, detail=resp.text)
    return resp.json()


async def cache_delete(hash_str: str) -> dict[str, Any]:
    """Forward DELETE /api/cache/{hash} to xstream_bt."""
    base = get_base_url()
    assert base is not None
    try:
        resp = await _get_client().delete(f"{base}/api/cache/{hash_str}", timeout=15.0)
    except httpx.HTTPError as exc:
        log.error(f"xstream_bt cache_delete failed: {exc}")
        raise HTTPException(status_code=503, detail="BitTorrent daemon unavailable")
    if resp.status_code == 404:
        raise HTTPException(status_code=404, detail="Torrent not found")
    if resp.status_code >= 400:
        raise HTTPException(status_code=resp.status_code, detail=resp.text)
    _stop_watch(hash_str)
    return resp.json()


async def cache_evict() -> dict[str, Any]:
    """Forward POST /api/cache/evict to xstream_bt."""
    base = get_base_url()
    assert base is not None
    try:
        resp = await _get_client().post(f"{base}/api/cache/evict", timeout=30.0)
    except httpx.HTTPError as exc:
        log.error(f"xstream_bt cache_evict failed: {exc}")
        raise HTTPException(status_code=503, detail="BitTorrent daemon unavailable")
    if resp.status_code >= 400:
        raise HTTPException(status_code=resp.status_code, detail=resp.text)
    return resp.json()


async def set_pin(hash_str: str, *, pinned: bool) -> None:
    """Sync liked/pinned protection state for a torrent hash to xstream_bt (best-effort)."""
    base = get_base_url()
    if not base or not hash_str:
        return
    try:
        method = "POST" if pinned else "DELETE"
        await _get_client().request(method, f"{base}/api/cache/pin/{hash_str}", timeout=5.0)
    except Exception as exc:
        log.warning(f"xstream_bt pin sync failed for {hash_str[:12]}: {exc}")
