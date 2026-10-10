"""tests/test_cover_bytea.py — title_covers stores raw bytes (BYTEA)

Locks the one-shot cover_b64 → cover_data migration (data-URI prefix
stripped, plain base64 decoded, empty rows left NULL, idempotent) and the
cover_bytes boundary helper used by every writer.
"""

from __future__ import annotations

import base64

from core import db


def test_cover_bytes_accepts_all_pipeline_forms():
    raw = b"\xff\xd8\xff\xe0jpeg"
    b64 = base64.b64encode(raw).decode()
    assert db.cover_bytes(f"data:image/jpeg;base64,{b64}") == raw
    assert db.cover_bytes(b64) == raw
    assert db.cover_bytes(raw) == raw
    assert db.cover_bytes(memoryview(raw)) == raw
    assert db.cover_bytes("") is None
    assert db.cover_bytes(None) is None


def test_migrate_cover_b64_to_bytea(pg_test_db):
    conn = pg_test_db
    raw = b"\x89PNG\r\n\x1a\nimage"
    b64 = base64.b64encode(raw).decode()
    conn.execute("INSERT INTO stars (id, name) VALUES (1, 'S')")
    conn.execute(
        "INSERT INTO titles (id, star_id, code) VALUES (1, 1, 'A-1'), (2, 1, 'A-2'), (3, 1, 'A-3')"
    )
    conn.execute("ALTER TABLE title_covers DROP COLUMN cover_data")
    conn.execute("ALTER TABLE title_covers ADD COLUMN cover_b64 TEXT")
    conn.execute(
        "INSERT INTO title_covers (title_id, cover_b64) VALUES (1, %s), (2, %s), (3, '')",
        (f"data:image/png;base64,{b64}", b64),
    )

    db.init_schema(conn)
    db.init_schema(conn)

    rows = dict(conn.execute("SELECT title_id, cover_data FROM title_covers").fetchall())
    assert bytes(rows[1]) == raw
    assert bytes(rows[2]) == raw
    assert rows[3] is None
    assert conn.execute(
        "SELECT 1 FROM information_schema.columns"
        " WHERE table_name = 'title_covers' AND column_name = 'cover_b64'"
    ).fetchone() is None
