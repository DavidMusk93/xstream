"""core/db/write_queue.py — Bounded-concurrency async DB executor.

Previously serialized all writes through a single worker coroutine (a holdover
from the DuckDB single-writer era). PostgreSQL handles concurrent row-level
writes natively, so writes now execute concurrently in worker threads under a
bounded semaphore (preserving pool headroom for reads), while per-star sync
correctness is enforced in PostgreSQL via ``pg_advisory_xact_lock``.

The public API (``DBWriteQueue``, ``get_queue``, ``db_write``, ``db_read``) is
kept backwards-compatible for all call sites.
"""

from __future__ import annotations

import asyncio
import functools
import time
from typing import Any, Callable

from core.logger import get_logger

log = get_logger("db-write-queue")

DEFAULT_MAX_CONCURRENT_WRITES = 8


class DBWriteQueue:
    """Run synchronous DB write callables off the event loop with bounded concurrency.

    Each write checks out its own pooled connection from ``core.db.connection._conn``
    and runs via ``asyncio.to_thread``. Bounding concurrency to less than half of
    ``POOL_MAX_SIZE`` prevents write bursts from starving concurrent reads.
    """

    def __init__(self, maxsize: int = 0, max_concurrency: int = DEFAULT_MAX_CONCURRENT_WRITES):
        self._maxsize = maxsize
        self._max_concurrency = max(1, max_concurrency)
        self._sem: asyncio.Semaphore | None = None
        self._sem_loop: asyncio.AbstractEventLoop | None = None
        self._started = False

    def _get_semaphore(self) -> asyncio.Semaphore:
        loop = asyncio.get_running_loop()
        if self._sem is None or self._sem_loop is not loop:
            self._sem = asyncio.Semaphore(self._max_concurrency)
            self._sem_loop = loop
        return self._sem

    def start(self) -> None:
        """Initialize semaphore in the running event loop (idempotent)."""
        try:
            self._get_semaphore()
        except RuntimeError as exc:
            raise RuntimeError("DB write queue must be started inside a running event loop") from exc
        if not self._started:
            self._started = True
            log.info(f"DB write executor ready (max_concurrency={self._max_concurrency})")

    async def enqueue(self, func: Callable, *args, **kwargs) -> Any:
        """Execute a synchronous write callable in a worker thread under the concurrency cap."""
        self.start()
        sem = self._get_semaphore()
        enqueue_ts = time.perf_counter()
        async with sem:
            start = time.perf_counter()
            try:
                if kwargs:
                    bound = functools.partial(func, **kwargs)
                    result = await asyncio.to_thread(bound, *args)
                else:
                    result = await asyncio.to_thread(func, *args)
                elapsed = (time.perf_counter() - start) * 1000
                log.debug(f"{func.__name__} -> ok ({elapsed:.1f}ms)")
            except Exception as exc:
                elapsed = (time.perf_counter() - start) * 1000
                log.error(f"{func.__name__} -> {type(exc).__name__}: {exc} ({elapsed:.1f}ms)")
                raise
        wait_ms = (time.perf_counter() - enqueue_ts) * 1000
        if wait_ms > 100:
            log.warning(f"{func.__name__} total wait={wait_ms:.1f}ms")
        return result

    async def stop(self) -> None:
        """Graceful shutdown (no persistent worker task to drain)."""
        self._started = False
        self._sem = None
        self._sem_loop = None
        log.info("DB write executor stopped")


# Global singleton (process-level)
_default_queue = DBWriteQueue()


def get_queue() -> DBWriteQueue:
    return _default_queue


async def db_write(func: Callable, *args, **kwargs) -> Any:
    """Execute a synchronous DB write off the event loop with bounded concurrency."""
    return await _default_queue.enqueue(func, *args, **kwargs)


async def db_read(func: Callable, *args, **kwargs) -> Any:
    """Run a synchronous read in a worker thread, bypassing the write semaphore."""
    return await asyncio.to_thread(func, *args, **kwargs)
