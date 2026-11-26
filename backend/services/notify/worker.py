"""Durable outbound notification worker backed by PostgreSQL notify_outbox.

Single serial async consumer with:
- Reused httpx.AsyncClient connection pool
- Global per-chat rate pacing (avoids Telegram 429 bursts on multi-card syncs)
- Chunk-level progress persistence (resumes from failed chunk without duplicates)
- Classified error handling: 429 Retry-After, exponential backoff on 5xx/timeout,
  dead-letter on permanent 4xx or exhausted retries
- Graceful drain on backend shutdown
"""

from __future__ import annotations

import asyncio
import time
from typing import Any

import httpx

from backend.services.notify import telegram as telegram_mod
from core import db
from core.db.write_queue import db_read, db_write
from core.logger import get_logger

log = get_logger("notify")

DEFAULT_BACKOFF_SCHEDULE: tuple[float, ...] = (5.0, 15.0, 60.0, 180.0, 600.0)
DEFAULT_MAX_ATTEMPTS = 6
DEFAULT_MIN_SEND_INTERVAL = 1.05
DEFAULT_POLL_INTERVAL = 30.0
PRUNE_INTERVAL_SEC = 3600.0


class NotifyWorker:
    """Single-consumer durable outbox dispatcher for Telegram notifications."""

    def __init__(
        self,
        *,
        min_send_interval: float = DEFAULT_MIN_SEND_INTERVAL,
        max_attempts: int = DEFAULT_MAX_ATTEMPTS,
        backoff_schedule: tuple[float, ...] = DEFAULT_BACKOFF_SCHEDULE,
        poll_interval: float = DEFAULT_POLL_INTERVAL,
    ) -> None:
        self._min_send_interval = min_send_interval
        self._max_attempts = max_attempts
        self._backoff_schedule = backoff_schedule
        self._poll_interval = poll_interval

        self._wakeup = asyncio.Event()
        self._stop_event = asyncio.Event()
        self._task: asyncio.Task[Any] | None = None
        self._client: httpx.AsyncClient | None = None
        self._last_send_mono: float = 0.0
        self._last_prune_mono: float = 0.0

    @property
    def running(self) -> bool:
        return self._task is not None and not self._task.done()

    def start(self) -> None:
        """Idempotently start the background worker loop."""
        if self.running:
            return
        self._stop_event.clear()
        self._wakeup.clear()
        self._task = asyncio.create_task(self._run(), name="notify-worker")
        log.info("notify worker started")

    def wake(self) -> None:
        """Signal the worker that a new outbox row is ready."""
        self._wakeup.set()

    async def stop(self, drain_timeout: float = 5.0) -> None:
        """Signal shutdown and wait briefly for any in-flight HTTP call to finish."""
        if self._task is None:
            return
        self._stop_event.set()
        self._wakeup.set()
        try:
            await asyncio.wait_for(self._task, timeout=drain_timeout)
        except asyncio.TimeoutError:
            log.warning(f"notify worker did not stop within {drain_timeout}s; cancelling")
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        except asyncio.CancelledError:
            pass
        finally:
            self._task = None
            if self._client is not None:
                await self._client.aclose()
                self._client = None
        log.info("notify worker stopped")

    def _backoff_for(self, attempt_number: int) -> float:
        idx = min(max(0, attempt_number - 1), len(self._backoff_schedule) - 1)
        return self._backoff_schedule[idx]

    async def _pace(self) -> None:
        if self._min_send_interval <= 0:
            return
        elapsed = time.monotonic() - self._last_send_mono
        wait = self._min_send_interval - elapsed
        if wait > 0:
            try:
                await asyncio.wait_for(self._stop_event.wait(), timeout=wait)
            except asyncio.TimeoutError:
                pass

    async def _maybe_prune(self) -> None:
        now = time.monotonic()
        if now - self._last_prune_mono < PRUNE_INTERVAL_SEC:
            return
        self._last_prune_mono = now
        try:
            removed = await db_write(db.prune_old_notifications, 14)
            if removed:
                log.info(f"pruned {removed} old notify_outbox rows")
        except Exception:
            log.exception("failed to prune old notify_outbox rows")

    async def process_once(self) -> int:
        """Drain currently due outbox rows once. Returns number of rows processed."""
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=telegram_mod._SEND_TIMEOUT)

        rows = await db_read(db.fetch_due_notifications, 10)
        if not rows:
            return 0

        processed = 0
        for row in rows:
            if self._stop_event.is_set():
                break
            await self._deliver_row(row)
            processed += 1
        return processed

    async def _deliver_row(self, row: dict[str, Any]) -> None:
        outbox_id: int = row["id"]
        event: str = row["event"]
        parse_mode: str | None = row["parse_mode"]
        chunks: list[str] = row["chunks"]
        sent_chunks: int = row["sent_chunks"]
        attempts: int = row["attempts"]
        total_chunks = len(chunks)

        if total_chunks == 0 or sent_chunks >= total_chunks:
            await db_write(db.mark_notification_sent, outbox_id, total_chunks)
            return

        assert self._client is not None
        for idx in range(sent_chunks, total_chunks):
            if self._stop_event.is_set():
                # Persist partial progress and leave pending for next startup
                if idx > sent_chunks:
                    await db_write(db.advance_notification_progress, outbox_id, idx)
                return

            await self._pace()
            if self._stop_event.is_set():
                if idx > sent_chunks:
                    await db_write(db.advance_notification_progress, outbox_id, idx)
                return

            self._last_send_mono = time.monotonic()
            outcome = await telegram_mod.send_chunk(
                self._client, chunks[idx], parse_mode=parse_mode
            )

            if outcome.ok:
                new_sent = idx + 1
                if new_sent < total_chunks:
                    await db_write(db.advance_notification_progress, outbox_id, new_sent)
                else:
                    await db_write(db.mark_notification_sent, outbox_id, total_chunks)
                    log.info(
                        f"notify delivered: id={outbox_id} event={event} chunks={total_chunks}"
                    )
                continue

            next_attempts = attempts + 1
            if not outcome.retryable or next_attempts >= self._max_attempts:
                await db_write(
                    db.mark_notification_dead,
                    outbox_id,
                    idx,
                    next_attempts,
                    outcome.error or "unknown error",
                )
                log.error(
                    f"notify dead-lettered: id={outbox_id} event={event} "
                    f"chunk={idx + 1}/{total_chunks} attempts={next_attempts} "
                    f"error={outcome.error}"
                )
                return

            delay = self._backoff_for(next_attempts)
            if outcome.retry_after is not None:
                delay = max(delay, outcome.retry_after + 0.5)

            await db_write(
                db.schedule_notification_retry,
                outbox_id,
                idx,
                next_attempts,
                delay,
                outcome.error or "transient error",
            )
            log.warning(
                f"notify retry scheduled: id={outbox_id} event={event} "
                f"chunk={idx + 1}/{total_chunks} attempt={next_attempts}/{self._max_attempts} "
                f"in {delay:.1f}s ({outcome.error})"
            )
            return

    async def _run(self) -> None:
        self._client = httpx.AsyncClient(timeout=telegram_mod._SEND_TIMEOUT)
        try:
            while not self._stop_event.is_set():
                try:
                    await self._maybe_prune()
                    processed = await self.process_once()
                    if processed > 0 and not self._stop_event.is_set():
                        # Immediately check if more rows are due
                        continue
                except asyncio.CancelledError:
                    raise
                except Exception:
                    log.exception("notify worker loop error")

                if self._stop_event.is_set():
                    break

                wait_sec = self._poll_interval
                try:
                    next_delay = await db_read(db.next_pending_delay)
                    if next_delay is not None:
                        wait_sec = min(wait_sec, max(0.05, next_delay))
                except Exception:
                    log.exception("notify worker failed to query next_pending_delay")

                self._wakeup.clear()
                try:
                    await asyncio.wait_for(self._wakeup.wait(), timeout=wait_sec)
                except asyncio.TimeoutError:
                    pass
        finally:
            if self._client is not None:
                await self._client.aclose()
                self._client = None
