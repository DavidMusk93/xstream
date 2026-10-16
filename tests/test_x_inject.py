"""tests/test_x_inject.py — Injected X profiles (no X API)

Locks the inject contract agents rely on: x.com HTML, plain text and JSON
(single + batch) all parse to the same normalized profile; only
pbs.twimg.com media / x.com status links survive (media rewritten to the
"small" variant); post time falls back to the status-id snowflake; at most
5 posts are kept; re-injects merge by post id, a new handle replaces the
account, "not found" clears it but stamps the check; /api/stars ships it.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.services.x_inject import (
    InjectError,
    clean_media,
    parse_count,
    parse_payload,
    snowflake_time,
)

STATUS = "https://x.com/yua_mikami/status/1846000000000000000"

X_HTML = """
<html><head><link rel="canonical" href="https://x.com/yua_mikami"></head><body>
<div data-testid="UserName"><span>三上悠亜</span><span>@yua_mikami</span></div>
<article data-testid="tweet">
  <div data-testid="socialContext">Pinned</div>
  <img src="https://pbs.twimg.com/profile_images/123/abc_normal.jpg">
  <a href="/yua_mikami/status/1700000000000000000"><time datetime="2023-09-08T04:00:00.000Z">Sep 8</time></a>
  <div data-testid="tweetText"><span>Old pinned </span><img alt="✨"></div>
</article>
<article data-testid="tweet">
  <a href="/yua_mikami/status/1846000000000000000"><time datetime="2024-10-15T03:00:00.000Z">Oct 15</time></a>
  <div data-testid="tweetText"><span>New post</span></div>
  <div data-testid="tweetPhoto"><img src="https://pbs.twimg.com/media/GZabc?format=jpg&amp;name=large"></div>
  <img src="https://evil.example/track.gif">
  <button data-testid="reply" aria-label="12 Replies. Reply"></button>
  <button data-testid="retweet" aria-label="3.4K reposts. Repost"></button>
  <button data-testid="like" aria-label="56,789 Likes. Like"></button>
  <a href="/yua_mikami/status/1846000000000000000/analytics" aria-label="1.2M views. View post analytics"></a>
</article>
</body></html>
"""


def test_html_profile_and_posts():
    [p] = parse_payload(X_HTML, "MIDV-001")
    assert (p.star, p.handle, p.name) == ("MIDV-001", "yua_mikami", "三上悠亜")
    assert p.avatar == "https://pbs.twimg.com/profile_images/123/abc_bigger.jpg"
    assert [x.text for x in p.posts] == ["New post", "Old pinned ✨"]
    new, old = p.posts
    assert new.url == STATUS and new.id == "1846000000000000000"
    assert new.posted_at == datetime(2024, 10, 15, 3, 0)
    assert new.media == ["https://pbs.twimg.com/media/GZabc?format=jpg&name=small"]
    assert new.stats == {"replies": 12, "reposts": 3400, "likes": 56789, "views": 1_200_000}
    assert old.pinned and not new.pinned


def test_text_blocks_with_separators():
    text = f"""@yua_mikami
---
{STATUS}
Hello world
second line
likes: 1.5K
https://pbs.twimg.com/media/AAA.png
---
just text, no link
time: 2024-01-02T03:04:05Z
"""
    [p] = parse_payload(text, "MIDV-001")
    assert p.handle == "yua_mikami"
    a, b = p.posts
    assert a.text == "Hello world\nsecond line"
    assert a.stats == {"likes": 1500}
    assert a.media == ["https://pbs.twimg.com/media/AAA?format=png&name=small"]
    assert a.posted_at == snowflake_time("1846000000000000000")
    assert b.url is None and b.id.startswith("h") and b.posted_at == datetime(2024, 1, 2, 3, 4, 5)


def test_text_without_separators_splits_on_status_urls_and_infers_handle():
    text = f"{STATUS}\nfirst\nhttps://x.com/yua_mikami/status/1846000000000000001\nsecond"
    [p] = parse_payload(text, "MIDV-001")
    assert p.handle == "yua_mikami"
    assert sorted(x.text for x in p.posts) == ["first", "second"]


@pytest.mark.parametrize("payload", ["none", "Not found", "无", '{"handle": null}', {"found": False}])
def test_not_found_markers(payload):
    [p] = parse_payload(payload, "MIDV-001")
    assert p.not_found and p.handle is None and p.posts == []


def test_json_batch_and_limits():
    posts = [{"url": f"https://x.com/a_b/status/{1846000000000000000 + i}", "text": f"p{i}"} for i in range(8)]
    out = parse_payload({"stars": [
        {"star": "MIDV-001", "handle": "@a_b", "posts": posts},
        {"star": "SSIS-001", "handle": None},
    ]})
    assert [p.star for p in out] == ["MIDV-001", "SSIS-001"]
    assert [x.text for x in out[0].posts] == ["p7", "p6", "p5", "p4", "p3"]
    assert out[1].not_found


def test_rejects_garbage():
    with pytest.raises(InjectError):
        parse_payload("   ")
    with pytest.raises(InjectError):
        parse_payload('{"handle": "not a handle!!"}', "X")
    with pytest.raises(InjectError):
        parse_payload("{broken", "X")


def test_media_and_count_normalizers():
    assert clean_media("http://pbs.twimg.com/media/A.jpg") is None
    assert clean_media("https://evil.com/media/A.jpg") is None
    assert clean_media("https://pbs.twimg.com/ext_tw_video_thumb/1/pu/img/x.jpg").endswith("x.jpg")
    assert parse_count("3万") == 30000 and parse_count("12,345") == 12345 and parse_count("") is None
    assert snowflake_time("12345") is None


# ── DB + endpoint ───────────────────────────────────────────────────

@pytest.fixture
def client(pg_test_db):
    from backend.routers import social, stars
    from backend.routers.auth import require_auth
    from core import db

    db.upsert_star("Yua", jp_name="三上悠亜", handle="yua_mikami", code="MIDV-001")
    app = FastAPI()
    app.include_router(social.router)
    app.dependency_overrides[require_auth] = lambda: None
    stars.invalidate_stars_cache()
    return TestClient(app)


def _stored():
    from core import db
    return db.load_x_profiles()["MIDV-001"]


def _post(i: int, text: str | None = None) -> dict:
    return {"url": f"https://x.com/yua_mikami/status/{1846000000000000000 + i}", "text": text or f"p{i}"}


def test_inject_merge_switch_and_clear(client):
    r = client.post("/api/social/x", json={"star": "midv-001", "content": X_HTML})
    assert r.status_code == 200, r.text
    assert r.json()["results"][0]["posts"] == 2
    assert _stored()["handle"] == "yua_mikami" and _stored()["avatar"].endswith("_bigger.jpg")
    # Shipped with a "Z" suffix, so it must really be UTC whatever the server TZ.
    checked = datetime.fromisoformat(_stored()["checked_at"].replace("Z", "+00:00"))
    assert abs((datetime.now(UTC) - checked).total_seconds()) < 120

    # Merge by id: 4 new + 2 stored -> newest 5; an edited text replaces in place.
    content = {"posts": [_post(1), _post(2), _post(3), _post(0, "New post edited")]}
    client.post("/api/social/x", json={"star": "三上悠亜", "content": content})
    texts = [p["text"] for p in _stored()["posts"]]
    assert texts == ["p3", "p2", "p1", "New post edited", "Old pinned ✨"]
    assert _stored()["name"] == "三上悠亜"

    # Different handle replaces the account and its posts.
    client.post("/api/social/x", json={"star": "MIDV-001", "content": {"handle": "other_acc", "posts": []}})
    assert _stored()["handle"] == "other_acc" and _stored()["posts"] == []

    client.post("/api/social/x", json={"star": "MIDV-001", "content": "none"})
    stored = _stored()
    assert stored["handle"] is None and stored["checked_at"]

    pending = client.get("/api/social/x/pending", params={"stale_hours": 0}).json()
    assert pending["inject"]["endpoint"] == "POST /api/social/x"
    assert client.get("/api/social/x/pending").json()["count"] == 0


def test_inject_errors(client):
    assert client.post("/api/social/x", json={"star": "nobody", "content": "none"}).status_code == 404
    assert client.post("/api/social/x", json={"content": "none"}).status_code == 404
    assert client.post("/api/social/x", json={"star": "MIDV-001", "content": ""}).status_code == 422
