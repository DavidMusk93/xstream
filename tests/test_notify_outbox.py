"""Locks notify_outbox PG persistence, chunk resume, retry scheduling, and dead-lettering."""

from __future__ import annotations

from core import db


def test_outbox_enqueue_progress_and_sent(pg_test_db):
    oid = db.enqueue_notification("sync.completed", ["header", "card1", "card2"], "HTML")
    due = db.fetch_due_notifications(limit=10)
    assert len(due) == 1
    assert due[0]["id"] == oid
    assert due[0]["event"] == "sync.completed"
    assert due[0]["chunks"] == ["header", "card1", "card2"]
    assert due[0]["sent_chunks"] == 0
    assert due[0]["attempts"] == 0

    db.advance_notification_progress(oid, 1)
    due2 = db.fetch_due_notifications(limit=10)
    assert due2[0]["sent_chunks"] == 1

    db.mark_notification_sent(oid, 3)
    assert db.fetch_due_notifications(limit=10) == []
    assert db.next_pending_delay() is None

    stats = db.get_notify_outbox_stats()
    assert stats["pending"] == 0
    assert stats["sent"] == 1
    assert stats["dead"] == 0
    assert stats["recent_errors"] == []


def test_outbox_retry_delay_and_dead_letter(pg_test_db):
    oid = db.enqueue_notification("sync.error", ["boom"], "HTML")
    db.schedule_notification_retry(oid, sent_chunks=0, attempts=1, delay_seconds=60.0, error="ReadTimeout")

    # Not due yet
    assert db.fetch_due_notifications(limit=10) == []
    delay = db.next_pending_delay()
    assert delay is not None and 30.0 <= delay <= 65.0

    stats = db.get_notify_outbox_stats()
    assert stats["pending"] == 1
    assert len(stats["recent_errors"]) == 1
    assert stats["recent_errors"][0]["last_error"] == "ReadTimeout"

    db.mark_notification_dead(oid, sent_chunks=0, attempts=5, error="exhausted")
    stats_dead = db.get_notify_outbox_stats()
    assert stats_dead["pending"] == 0
    assert stats_dead["dead"] == 1
    assert stats_dead["recent_errors"][0]["status"] == "dead"
