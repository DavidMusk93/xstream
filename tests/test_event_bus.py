"""tests/test_event_bus.py — Regression tests for the Rust-backed SSE EventBus."""

from __future__ import annotations

import asyncio
import json

import pytest

from core.events import EventBus


@pytest.mark.asyncio
async def test_event_bus_publish_and_receive():
    bus = EventBus(capacity=16)
    sub1 = await bus.subscribe()
    sub2 = await bus.subscribe()

    await bus.publish("star.added", {"code": "SNOS-524"})

    p1 = json.loads(await asyncio.wait_for(sub1.get(), timeout=1.0))
    p2 = json.loads(await asyncio.wait_for(sub2.get(), timeout=1.0))
    assert p1["event"] == "star.added"
    assert p1["data"] == {"code": "SNOS-524"}
    assert p2["event"] == "star.added"

    await bus.unsubscribe(sub1)
    await bus.unsubscribe(sub2)


@pytest.mark.asyncio
async def test_event_bus_coalesces_slow_client_to_resync():
    bus = EventBus(capacity=2)
    slow = await bus.subscribe()
    fast = await bus.subscribe()

    await bus.publish("e1", {"n": 1})
    assert json.loads(await fast.get())["event"] == "e1"
    await bus.publish("e2", {"n": 2})
    assert json.loads(await fast.get())["event"] == "e2"

    # Third event overflows slow (capacity=2) -> coalesced to sync.resync_required
    await bus.publish("e3", {"n": 3})

    assert json.loads(await slow.get())["event"] == "sync.resync_required"
    assert json.loads(await fast.get())["event"] == "e3"

    await bus.unsubscribe(slow)
    await bus.unsubscribe(fast)
