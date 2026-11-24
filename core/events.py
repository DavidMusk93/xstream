"""core/events.py — In-process event bus for SSE push (Rust-backed)

Subscriber registry, bounded per-client ring buffers, and slow-client
``sync.resync_required`` coalescing live in ``xstream_core.EventBus`` (Rust).
Each subscriber receives a thin async ``EventSubscription`` adapter with an
``asyncio.Event`` wakeup so SSE endpoints await events without per-client OS
threads.
"""

from __future__ import annotations

import asyncio
import json
import time
from typing import Any

import xstream_core

from core.logger import get_logger

log = get_logger("events")


class EventSubscription:
    """Async queue-compatible view over a single Rust ``EventBus`` subscriber."""

    def __init__(self, bus: xstream_core.EventBus, sub_id: int) -> None:
        self._bus = bus
        self.sub_id = sub_id
        self._wakeup = asyncio.Event()

    def notify(self) -> None:
        """Signal the awaiting SSE consumer that at least one payload is ready."""
        self._wakeup.set()

    async def get(self) -> str:
        """Await and return the next JSON-encoded SSE payload."""
        while True:
            item = self._bus.try_recv(self.sub_id)
            if item is not None:
                return item
            self._wakeup.clear()
            # Re-check after clear to close the publish/clear race window.
            item = self._bus.try_recv(self.sub_id)
            if item is not None:
                return item
            await self._wakeup.wait()

    def get_nowait(self) -> str:
        """Return the next buffered payload or raise ``asyncio.QueueEmpty``."""
        item = self._bus.try_recv(self.sub_id)
        if item is None:
            raise asyncio.QueueEmpty
        return item


class EventBus:
    """Async pub/sub bus backed by thread-safe ``xstream_core.EventBus``."""

    def __init__(self, capacity: int = 256) -> None:
        self._rust_bus = xstream_core.EventBus(capacity)
        self._subs: dict[int, EventSubscription] = {}

    async def subscribe(self) -> EventSubscription:
        """Register a new subscriber and return an async queue-like handle."""
        sub_id = self._rust_bus.subscribe()
        sub = EventSubscription(self._rust_bus, sub_id)
        self._subs[sub_id] = sub
        log.debug(f"SSE client subscribed, total={self._rust_bus.subscriber_count()}")
        return sub

    async def unsubscribe(self, sub: EventSubscription) -> None:
        """Remove a subscriber and drop its buffered events."""
        self._subs.pop(sub.sub_id, None)
        self._rust_bus.unsubscribe(sub.sub_id)
        log.debug(f"SSE client unsubscribed, total={self._rust_bus.subscriber_count()}")

    async def publish(self, event: str, data: dict[str, Any]) -> None:
        """Broadcast an event to all connected clients.

        Slow-client policy (coalesce + resync, not disconnect): handled
        atomically inside ``xstream_core.EventBus.publish``.
        """
        now = time.time()
        payload = json.dumps({"event": event, "data": data, "ts": now})
        marker = json.dumps({"event": "sync.resync_required", "data": {}, "ts": now})
        notified, coalesced = self._rust_bus.publish(payload, marker)
        for sub_id in notified:
            sub = self._subs.get(sub_id)
            if sub is not None:
                sub.notify()
        if coalesced:
            total_clients = self._rust_bus.subscriber_count()
            for _, dropped in coalesced:
                log.warning(
                    f"SSE slow client coalesced: dropped {dropped} events, "
                    f"sent sync.resync_required (clients={total_clients})"
                )


# Global singleton
_bus = EventBus()


def get_bus() -> EventBus:
    return _bus


async def publish_event(event: str, data: dict[str, Any]) -> None:
    await _bus.publish(event, data)
    try:
        from backend.services.notify import schedule_dispatch

        schedule_dispatch(event, data)
    except Exception:
        log.exception(f"notify hook failed for {event}")
