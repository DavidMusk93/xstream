"""Notify hook registry — one row per outbound event point.

SSE event names and notify hooks share the same string id where both fire;
see docs/design/notifications.md.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class NotifyHook:
    event: str
    description: str
    default: bool = False


HOOKS: tuple[NotifyHook, ...] = (
    NotifyHook("sync.completed", "Library sync finished — per-star new titles", True),
    NotifyHook("sync.error", "Library sync failed", True),
    NotifyHook("sync.started", "Library sync started (4h scheduler or manual)", False),
    NotifyHook("metrics.alert", "Abnormal play / client metrics (timeout, error)", True),
    NotifyHook("magnets.check_completed", "Magnet liveness check finished", True),
    NotifyHook("magnets.check_error", "Magnet check failed", True),
    NotifyHook("magnets.purged", "Dead-magnet TTL purge", True),
    NotifyHook("magnets.check_started", "Magnet check started", False),
    NotifyHook("star.ready", "New star shelf ready", False),
    NotifyHook("star.social", "X inject for library stars", False),
    NotifyHook("creator.social", "X inject for pornographic creators", False),
)

CATALOG: dict[str, str] = {h.event: h.description for h in HOOKS}
DEFAULT_EVENTS: frozenset[str] = frozenset(h.event for h in HOOKS if h.default)
