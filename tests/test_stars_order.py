"""tests/test_stars_order.py — Home shelf order and follow time

``/api/stars`` stays ordered by each star's newest playable title. Follow
time is ``stars.created_at``, exposed as ``added_at`` so the home page can
reorder without a second query. A star followed later with an older title
must still sort behind a star whose newest work is newer.
"""

from __future__ import annotations

import json

import pytest


@pytest.fixture()
def stars_db(pg_test_db, tmp_path, monkeypatch):
    from backend.routers import stars

    cfg = {
        "stars": [
            {"name": "Alpha", "code": "AAA-001"},
            {"name": "Beta", "code": "BBB-001"},
        ]
    }
    path = tmp_path / "config.json"
    path.write_text(json.dumps(cfg), encoding="utf-8")
    monkeypatch.setattr(stars, "CONFIG_PATH", str(path))
    monkeypatch.setattr(stars, "IMAGES_DIR", str(tmp_path / "images"))
    pg_test_db.execute(
        "INSERT INTO stars (id, name, code, created_at) VALUES (1, 'Alpha', 'AAA-001', %s)",
        ("2026-10-01 08:00:00",),
    )
    pg_test_db.execute(
        "INSERT INTO stars (id, name, code, created_at) VALUES (2, 'Beta', 'BBB-001', %s)",
        ("2026-01-15 08:00:00",),
    )
    stars.invalidate_stars_cache()
    return pg_test_db


def test_payload_orders_by_newest_work_and_exposes_added_at(stars_db):
    """Alpha was followed later but her newest title is older, so Beta leads."""
    from backend.routers.stars import _build_stars_response

    stars_db.execute(
        """
        INSERT INTO titles (star_id, star_code, code, title, magnet, magnet_hash,
                            magnet_status, release_date, release_date_sort)
        VALUES (%s, 'X', %s, %s, 'm:', %s, 'ok', %s, %s)
        """,
        (1, "AAA-010", "old", "a" * 40, "1/1/2020", "20200101"),
    )
    stars_db.execute(
        """
        INSERT INTO titles (star_id, star_code, code, title, magnet, magnet_hash,
                            magnet_status, release_date, release_date_sort)
        VALUES (%s, 'X', %s, %s, 'm:', %s, 'ok', %s, %s)
        """,
        (2, "BBB-010", "new", "b" * 40, "15/6/2026", "20260615"),
    )

    payload = _build_stars_response()
    assert [s["code"] for s in payload] == ["BBB-001", "AAA-001"]
    by_code = {s["code"]: s for s in payload}
    assert by_code["AAA-001"]["added_at"].startswith("2026-10-01")
    assert by_code["BBB-001"]["added_at"].startswith("2026-01-15")


def test_discovery_date_breaks_release_date_ties(stars_db):
    """When two stars have works with the same release date,
    the work discovered more recently on xstream breaks the tie.
    """
    from datetime import datetime, timezone
    from backend.routers.stars import _build_stars_response

    today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    # Beta's work released 2026-08-01, discovered earlier
    stars_db.execute(
        """
        INSERT INTO titles (star_id, star_code, code, title, magnet, magnet_hash,
                            magnet_status, release_date, release_date_sort, created_at)
        VALUES (2, 'X', 'BBB-020', 'same release date earlier disc', 'm:', %s, 'ok', '1/8/2026', '20260801', '2026-01-01 10:00:00')
        """,
        ("b" * 40,),
    )
    # Alpha's work released 2026-08-01, discovered today
    stars_db.execute(
        """
        INSERT INTO titles (star_id, star_code, code, title, magnet, magnet_hash,
                            magnet_status, release_date, release_date_sort, created_at)
        VALUES (1, 'X', 'AAA-020', 'same release date recent disc', 'm:', %s, 'ok', '1/8/2026', '20260801', %s)
        """,
        ("a" * 40, today_str),
    )

    payload = _build_stars_response()
    # Same release date (20260801), so Alpha leads Beta due to newer discovery timestamp
    assert [s["code"] for s in payload] == ["AAA-001", "BBB-001"]
    assert payload[0]["titles"][0]["code"] == "AAA-020"
    assert "discovered_at" in payload[0]["titles"][0]
