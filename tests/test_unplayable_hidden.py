"""tests/test_unplayable_hidden.py — Unplayable works never reach the UI

A work whose magnet was checked dead (no live candidate) or that has no
magnet at all cannot be played, so it must not occupy a shelf slot:

1. ``/api/stars`` hides it — the payload is the single source of truth for
   the waterfall and the rail, so hiding here covers every consumer.
2. Liked rows are the exception: they stay visible (greyed by the card so the
   owner can unlike them) and are never purged.
3. The TTL purge retires the row only after DEAD_PURGE_TTL_DAYS, so a
   temporarily starved swarm can come back through the regular re-check;
   ``dead_since`` keeps the first dead time so a re-check cannot restart it.
"""

from __future__ import annotations

import pytest

from core import db


@pytest.fixture()
def stars_db(pg_test_db, tmp_path, monkeypatch):
    """xstream_test + a two-star config, no cover files on disk."""
    from backend.routers import stars

    cfg = {
        "stars": [
            {"name": "Alpha", "code": "AAA-001"},
            {"name": "Beta", "code": "BBB-001"},
        ]
    }
    path = tmp_path / "config.json"
    path.write_text(__import__("json").dumps(cfg), encoding="utf-8")
    monkeypatch.setattr(stars, "CONFIG_PATH", str(path))
    monkeypatch.setattr(stars, "IMAGES_DIR", str(tmp_path / "images"))
    pg_test_db.execute("INSERT INTO stars (id, name, code) VALUES (1, 'Alpha', 'AAA-001')")
    pg_test_db.execute("INSERT INTO stars (id, name, code) VALUES (2, 'Beta', 'BBB-001')")
    stars.invalidate_stars_cache()
    return pg_test_db


def _title(conn, star_id: int, code: str, *, status=None, magnet="m:", liked=0,
           dead_since=None):
    conn.execute(
        """
        INSERT INTO titles (star_id, star_code, code, title, magnet, magnet_hash,
                            magnet_status, dead_since, user_liked)
        VALUES (%s, 'X', %s, %s, %s, %s, %s, %s, %s)
        """,
        (star_id, code, f"title {code}", magnet, "a" * 40, status, dead_since, liked),
    )


def _codes(payload, star_index: int = 0) -> list[str]:
    return [t["code"] for t in payload[star_index]["titles"]]


def test_payload_hides_dead_and_magnetless_titles(stars_db):
    from backend.routers.stars import _build_stars_response

    _title(stars_db, 1, "AAA-001", status="ok")
    _title(stars_db, 1, "AAA-002", status="dead")
    _title(stars_db, 1, "AAA-003", magnet="")
    _title(stars_db, 1, "AAA-004", status="ok")

    payload = _build_stars_response()
    assert _codes(payload, 0) == ["AAA-004", "AAA-001"]


def test_payload_keeps_liked_unplayable_titles(stars_db):
    """A liked dead title stays visible so it can be unliked (and is never purged)."""
    from backend.routers.stars import _build_stars_response

    _title(stars_db, 1, "AAA-001", status="ok")
    _title(stars_db, 1, "AAA-002", status="dead", liked=1)

    payload = _build_stars_response()
    titles = {t["code"]: t for t in payload[0]["titles"]}
    assert set(titles) == {"AAA-001", "AAA-002"}
    assert titles["AAA-002"]["magnet_status"] == "dead"
    assert titles["AAA-002"]["user_liked"] is True


def test_payload_keeps_the_star_with_no_playable_titles(stars_db):
    """Hiding every title of a star must not drop the star (or renumber others)."""
    from backend.routers.stars import _build_stars_response

    _title(stars_db, 1, "AAA-001", status="dead")
    _title(stars_db, 2, "BBB-001", status="ok")

    payload = _build_stars_response()
    by_code = {s["code"]: s for s in payload}
    assert by_code["AAA-001"]["titles"] == []
    assert _codes(payload, payload.index(by_code["BBB-001"])) == ["BBB-001"]


def test_dead_since_is_sticky(stars_db):
    """A re-check keeps the first dead time — the TTL clock never restarts."""
    _title(stars_db, 1, "AAA-001")
    title_id = stars_db.execute("SELECT id FROM titles WHERE code = 'AAA-001'").fetchone()[0]

    db.update_magnet_check_dead(title_id, "a" * 40, conn=stars_db)
    first = stars_db.execute(
        "SELECT dead_since FROM titles WHERE id = %s", (title_id,)
    ).fetchone()[0]
    assert first is not None

    stars_db.execute(
        "UPDATE titles SET dead_since = now() - interval '5 days' WHERE id = %s", (title_id,)
    )
    db.update_magnet_check_dead(title_id, "a" * 40, conn=stars_db)
    again = stars_db.execute(
        "SELECT dead_since FROM titles WHERE id = %s", (title_id,)
    ).fetchone()[0]
    assert again < first  # the 5-day-old clock survived the second check


def test_revival_clears_dead_since(stars_db):
    _title(stars_db, 1, "AAA-001")
    title_id = stars_db.execute("SELECT id FROM titles WHERE code = 'AAA-001'").fetchone()[0]

    db.update_magnet_check_dead(title_id, "a" * 40, conn=stars_db)
    db.update_magnet_check_ok(title_id, "a" * 40, conn=stars_db)
    row = stars_db.execute(
        "SELECT magnet_status, dead_since FROM titles WHERE id = %s", (title_id,)
    ).fetchone()
    assert row == ("ok", None)

    db.update_magnet_check_dead(title_id, "b" * 40, conn=stars_db)
    db.swap_primary_magnet(title_id, "magnet:?xt=urn:btih:" + "c" * 40, "c" * 40, conn=stars_db)
    row = stars_db.execute(
        "SELECT magnet_status, dead_since FROM titles WHERE id = %s", (title_id,)
    ).fetchone()
    assert row == ("ok", None)


def test_ttl_filter_only_returns_rows_past_the_window(stars_db):
    _title(stars_db, 1, "AAA-001", status="dead",
           dead_since=__import__("datetime").datetime(2020, 1, 1))
    _title(stars_db, 1, "AAA-002", status="dead")  # dead just now
    _title(stars_db, 1, "AAA-003", status="ok")
    _title(stars_db, 1, "AAA-004", magnet="", status=None)  # created now
    stars_db.execute(
        "UPDATE titles SET created_at = now() - interval '30 days' WHERE code = 'AAA-004'"
    )

    everything = {t["code"] for t in db.list_unplayable_titles(conn=stars_db)}
    assert everything == {"AAA-001", "AAA-002", "AAA-004"}

    aged = {t["code"] for t in db.list_unplayable_titles(ttl_days=7, conn=stars_db)}
    assert aged == {"AAA-001", "AAA-004"}
