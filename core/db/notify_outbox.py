"""core/db/notify_outbox.py — Durable outbox queue for outbound notifications."""

from __future__ import annotations

from typing import Any

from psycopg.types.json import Jsonb

from .crud import _managed_conn


def enqueue_notification(
    event: str,
    chunks: list[str],
    parse_mode: str | None = "HTML",
    conn=None,
) -> int:
    """Persist a rendered notification into notify_outbox and return its id."""
    managed, should_close = _managed_conn(conn)
    try:
        row = managed.execute(
            """
            INSERT INTO notify_outbox (event, parse_mode, chunks)
            VALUES (%s, %s, %s)
            RETURNING id
            """,
            (event, parse_mode, Jsonb(list(chunks))),
        ).fetchone()
        return int(row[0])
    finally:
        if should_close:
            managed.close()


def fetch_due_notifications(limit: int = 10, conn=None) -> list[dict[str, Any]]:
    """Return pending notifications whose next_retry_at is due, oldest first."""
    managed, should_close = _managed_conn(conn)
    try:
        rows = managed.execute(
            """
            SELECT id, event, parse_mode, chunks, sent_chunks, attempts, last_error, created_at
            FROM notify_outbox
            WHERE status = 'pending' AND next_retry_at <= CURRENT_TIMESTAMP
            ORDER BY next_retry_at ASC, id ASC
            LIMIT %s
            """,
            (limit,),
        ).fetchall()
        return [
            {
                "id": r[0],
                "event": r[1],
                "parse_mode": r[2],
                "chunks": list(r[3] or []),
                "sent_chunks": int(r[4] or 0),
                "attempts": int(r[5] or 0),
                "last_error": r[6],
                "created_at": r[7],
            }
            for r in rows
        ]
    finally:
        if should_close:
            managed.close()


def next_pending_delay(conn=None) -> float | None:
    """Return seconds until the next pending row is due, or None if queue is empty."""
    managed, should_close = _managed_conn(conn)
    try:
        row = managed.execute(
            """
            SELECT EXTRACT(EPOCH FROM (MIN(next_retry_at) - CURRENT_TIMESTAMP))
            FROM notify_outbox
            WHERE status = 'pending'
            """
        ).fetchone()
        if not row or row[0] is None:
            return None
        return max(0.0, float(row[0]))
    finally:
        if should_close:
            managed.close()


def advance_notification_progress(
    outbox_id: int, sent_chunks: int, conn=None
) -> None:
    """Record how many chunks have already been delivered for chunk-level resume."""
    managed, should_close = _managed_conn(conn)
    try:
        managed.execute(
            "UPDATE notify_outbox SET sent_chunks = %s WHERE id = %s",
            (sent_chunks, outbox_id),
        )
    finally:
        if should_close:
            managed.close()


def mark_notification_sent(
    outbox_id: int, sent_chunks: int, conn=None
) -> None:
    """Mark a notification fully delivered."""
    managed, should_close = _managed_conn(conn)
    try:
        managed.execute(
            """
            UPDATE notify_outbox
            SET status = 'sent',
                sent_chunks = %s,
                sent_at = CURRENT_TIMESTAMP,
                last_error = NULL
            WHERE id = %s
            """,
            (sent_chunks, outbox_id),
        )
    finally:
        if should_close:
            managed.close()


def schedule_notification_retry(
    outbox_id: int,
    sent_chunks: int,
    attempts: int,
    delay_seconds: float,
    error: str,
    conn=None,
) -> None:
    """Keep row pending and schedule its next delivery attempt."""
    managed, should_close = _managed_conn(conn)
    try:
        managed.execute(
            """
            UPDATE notify_outbox
            SET sent_chunks = %s,
                attempts = %s,
                next_retry_at = CURRENT_TIMESTAMP + make_interval(secs => %s),
                last_error = %s
            WHERE id = %s
            """,
            (sent_chunks, attempts, max(0.0, float(delay_seconds)), error[:500], outbox_id),
        )
    finally:
        if should_close:
            managed.close()


def mark_notification_dead(
    outbox_id: int,
    sent_chunks: int,
    attempts: int,
    error: str,
    conn=None,
) -> None:
    """Move an exhausted notification to dead-letter status."""
    managed, should_close = _managed_conn(conn)
    try:
        managed.execute(
            """
            UPDATE notify_outbox
            SET status = 'dead',
                sent_chunks = %s,
                attempts = %s,
                last_error = %s
            WHERE id = %s
            """,
            (sent_chunks, attempts, error[:500], outbox_id),
        )
    finally:
        if should_close:
            managed.close()


def get_notify_outbox_stats(conn=None) -> dict[str, Any]:
    """Return status counts and recent failed/dead entries for operator status."""
    managed, should_close = _managed_conn(conn)
    try:
        counts = {"pending": 0, "sent": 0, "dead": 0}
        for status_val, cnt in managed.execute(
            "SELECT status, COUNT(*) FROM notify_outbox GROUP BY status"
        ).fetchall():
            if status_val in counts:
                counts[status_val] = int(cnt)
        recent_rows = managed.execute(
            """
            SELECT id, event, status, attempts, sent_chunks,
                   jsonb_array_length(chunks), last_error, created_at
            FROM notify_outbox
            WHERE status = 'dead' OR (status = 'pending' AND last_error IS NOT NULL)
            ORDER BY id DESC
            LIMIT 5
            """
        ).fetchall()
        recent_errors = [
            {
                "id": r[0],
                "event": r[1],
                "status": r[2],
                "attempts": int(r[3] or 0),
                "sent_chunks": int(r[4] or 0),
                "total_chunks": int(r[5] or 0),
                "last_error": r[6],
                "created_at": r[7].isoformat() if r[7] else None,
            }
            for r in recent_rows
        ]
        return {**counts, "recent_errors": recent_errors}
    finally:
        if should_close:
            managed.close()


def prune_old_notifications(retention_days: int = 14, conn=None) -> int:
    """Delete completed/dead outbox rows older than retention_days."""
    managed, should_close = _managed_conn(conn)
    try:
        cur = managed.execute(
            """
            DELETE FROM notify_outbox
            WHERE status IN ('sent', 'dead')
              AND created_at < CURRENT_TIMESTAMP - make_interval(days => %s)
            """,
            (retention_days,),
        )
        return int(cur.rowcount or 0)
    finally:
        if should_close:
            managed.close()
