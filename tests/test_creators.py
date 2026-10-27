"""tests/test_creators.py — Body creators (accounts the owner follows on X)

Creators are X accounts the owner follows that are NOT library stars: they
have no code, no titles and never touch the `stars` table. The external bot
injects them through POST /api/social/x/creators; each keeps the newest 10
posts (stars keep 5) and is shown in its own group inside the X overlay.

Locks: parser shape (`{"creators": [...]}` and single-creator payloads),
the 10-post cap, merge-by-id semantics, the not-found stamp that must not
erase a feed, and DELETE for unfollowing.
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.services.x_inject import parse_payload


def _post(i: int, text: str | None = None) -> dict:
    return {"url": f"https://x.com/a_body/status/{1846000000000000000 + i}",
            "text": text or f"c{i}"}


# ── Parser ─────────────────────────────────────────────────────────

def test_creators_batch_keeps_ten_posts():
    posts = [_post(i) for i in range(14)]
    [prof] = parse_payload({"creators": [{"handle": "@a_body", "name": "A Body", "posts": posts}]})
    assert prof.creator is True
    assert prof.handle == "a_body"
    assert [p.text for p in prof.posts] == [f"c{i}" for i in range(13, 3, -1)]


def test_star_profiles_still_keep_five_posts():
    posts = [_post(i) for i in range(8)]
    [prof] = parse_payload({"stars": [{"star": "MIDV-001", "handle": "yua", "posts": posts}]})
    assert prof.creator is False
    assert len(prof.posts) == 5


def test_single_creator_payload_defaults_to_creator_cap():
    """POST /creators passes creator=True: a bare single-profile JSON keeps 10."""
    posts = [_post(i) for i in range(12)]
    [prof] = parse_payload({"handle": "a_body", "posts": posts}, None, True)
    assert prof.creator is True and len(prof.posts) == 10
    assert prof.star is None


# ── DB + API ───────────────────────────────────────────────────────

@pytest.fixture()
def client(pg_test_db):
    from backend.routers import social
    from backend.routers.auth import require_auth

    app = FastAPI()
    app.include_router(social.router)
    app.dependency_overrides[require_auth] = lambda: None
    return TestClient(app)


def _creators() -> list[dict]:
    from core import db
    return db.load_creators()


def test_inject_merge_and_cap(client):
    posts = [_post(i) for i in range(12)]
    r = client.post("/api/social/x/creators", json={
        "content": {"creators": [{"handle": "a_body", "name": "A Body",
                                  "avatar": "https://pbs.twimg.com/profile_images/1/a_normal.jpg",
                                  "posts": posts}]}
    })
    assert r.status_code == 200, r.text
    assert r.json()["results"][0]["posts"] == 10

    [creator] = _creators()
    assert creator["handle"] == "a_body" and creator["name"] == "A Body"
    assert len(creator["posts"]) == 10
    assert creator["posts"][0]["text"] == "c11"

    # A later inject of the two newest posts keeps the stored timeline.
    client.post("/api/social/x/creators", json={
        "content": {"handle": "a_body", "posts": [_post(12), _post(13)]}
    })
    posts_now = _creators()[0]["posts"]
    assert len(posts_now) == 10
    assert [p["text"] for p in posts_now[:3]] == ["c13", "c12", "c11"]


def test_translation_patch_does_not_blank_text(client):
    client.post("/api/social/x/creators", json={"content": {"handle": "a_body", "posts": [_post(1)]}})
    client.post("/api/social/x/creators", json={
        "content": {"handle": "a_body", "posts": [
            {"url": "https://x.com/a_body/status/1846000000000000001", "en": "hello darling"},
        ]}
    })
    [post] = _creators()[0]["posts"]
    assert post["text"] == "c1" and post["en"] == "hello darling"


def test_not_found_keeps_the_stored_feed(client):
    client.post("/api/social/x/creators", json={"content": {"handle": "a_body", "posts": [_post(1)]}})
    r = client.post("/api/social/x/creators", json={"content": "none"})
    assert r.status_code == 422  # no handle in the payload: nothing to stamp

    r = client.post("/api/social/x/creators", json={
        "content": {"handle": "a_body", "found": False}
    })
    assert r.status_code == 200, r.text
    [creator] = _creators()
    assert len(creator["posts"]) == 1 and creator["checked_at"]


def test_unfollow_deletes_creator_and_posts(client):
    client.post("/api/social/x/creators", json={"content": {"handle": "a_body", "posts": [_post(1)]}})
    assert client.delete("/api/social/x/creators/a_body").json()["deleted"] is True
    assert _creators() == []
    assert client.delete("/api/social/x/creators/a_body").status_code == 404


def test_creators_never_touch_the_stars_table(client):
    client.post("/api/social/x/creators", json={"content": {"handle": "a_body", "posts": [_post(1)]}})
    from core import db
    assert db._conn().execute("SELECT count(*) FROM stars").fetchone()[0] == 0


def test_creators_are_listed_separately(client):
    client.post("/api/social/x/creators", json={"content": {"handle": "a_body", "posts": [_post(1)]}})
    body = client.get("/api/social/x/creators").json()
    assert body["count"] == 1
    assert body["creators"][0]["handle"] == "a_body"
    assert body["inject"]["endpoint"] == "POST /api/social/x/creators"
