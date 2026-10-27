"""tests/test_star_attribution.py — A star's shelf holds only her own works

Locks the three defenses against the "another actress's work under this star"
bug (short names collide in sukebei's full-text search: ``Ichika`` matched
Ichika Nagano / Ichika Hoshimiya / Ichika Sasa):

1. ``verify.card_belongs_to`` — positive-evidence-only attribution (page URL
   or name match); an empty card is "unknown", never "not hers".
2. ``verify.reject_misattributed`` — in-batch cards are judged locally,
   link-less codes cost one ijavtorrent lookup, fetch failures keep the work.
3. Sync wiring — phase A and phase B both drop misattributed items, and only
   NEW codes are looked up (existing rows never refetch).
4. ``other_star`` blacklist entries never expire (the attribution can't
   change), so a dropped work is not re-added (and re-covered) every sync.
"""

from __future__ import annotations

import pytest

from scrapers.v2.schemas import MagnetCandidate, StarConfig, StarLink, VideoItem
from scrapers.v2.verify import (
    card_belongs_to,
    fetch_card_links,
    item_belongs_to,
    reject_misattributed,
)

STAR = StarConfig(
    name="Ichika", jp="Ichika", code="JUR-822",
    star_page_url="https://ijavtorrent.com/actress/ichika-7384",
)
MAGNET = "magnet:?xt=urn:btih:" + "aa" * 20


class _Fetcher:
    """URL -> HTML (or Exception) with a call log."""

    def __init__(self, pages: dict[str, object]):
        self.pages = pages
        self.calls: list[str] = []

    async def fetch(self, url: str) -> str:
        self.calls.append(url)
        outcome = self.pages.get(url)
        if outcome is None:
            raise AssertionError(f"unexpected fetch: {url}")
        if isinstance(outcome, Exception):
            raise outcome
        return str(outcome)


def _card(code: str, *names: str) -> str:
    """Minimal ijavtorrent search page with one card naming `names`."""
    links = "".join(
        f'<a href="/actress/{n.lower().replace(" ", "-")}-1">{n}</a>' for n in names
    )
    return (
        "<html><body>"
        f'<div class="video-item"><a href="/movie/{code.lower()}-1">'
        f'<img alt="{code} sample"/></a>'
        f'<div class="mb-1">{links}</div><table></table></div>'
        "</body></html>"
    )


def _item(code: str, *names: str) -> VideoItem:
    return VideoItem(
        code=code,
        title=f"{code} title",
        magnets=[MagnetCandidate(magnet=MAGNET)],
        star_links=[
            StarLink(name=n, url=f"https://ijavtorrent.com/actress/{n.lower().replace(' ', '-')}-1")
            for n in names
        ],
    )


# ── Attribution verdict ─────────────────────────────────────────────

def test_card_matches_by_page_url_not_just_name():
    """The page URL is exact evidence even when the display name differs."""
    links = [StarLink(name="市川 イチカ", url="https://ijavtorrent.com/actress/ichika-7384/")]
    assert card_belongs_to(links, STAR) is True


def test_card_matches_by_name_case_insensitively():
    assert card_belongs_to([StarLink(name="  ichika ", url="https://other/x")], STAR) is True


def test_card_naming_another_actress_is_evidence_against():
    links = [StarLink(name="Ichika Nagano", url="https://ijavtorrent.com/actress/ichika-nagano-1")]
    assert card_belongs_to(links, STAR) is False


def test_card_without_actress_links_is_unknown_not_rejected():
    """No evidence must never mean "not hers" — a wrong drop loses a real work."""
    assert card_belongs_to([], STAR) is None
    assert item_belongs_to(_item("JUR-001"), STAR) is None


def test_own_alias_from_config_counts_as_hers():
    """DB stars.name is often the japanese name; the romaji alias must match too."""
    star = StarConfig(
        name="涼森れむ", jp="Remu Suzumori", code="ABF-338",
        star_page_url="https://ijavtorrent.com/actress/remu-suzumori-1",
    )
    links = [StarLink(name="Remu Suzumori", url="https://ijavtorrent.com/actress/remu-suzumori-1")]
    assert card_belongs_to(links, star) is True


# ── Lookup helper ───────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_fetch_card_links_returns_none_without_a_card():
    """No card for the code (ijav's shrunken catalog) is unknown, not evidence."""
    url = "https://ijavtorrent.com/?searchTerm=JUR-822"
    fetcher = _Fetcher({url: _card("JUR-821", "Someone Else")})
    assert await fetch_card_links(fetcher, "jur-822") is None


@pytest.mark.asyncio
async def test_fetch_card_links_survives_fetch_errors():
    url = "https://ijavtorrent.com/?searchTerm=JUR-822"
    fetcher = _Fetcher({url: TimeoutError("down")})
    assert await fetch_card_links(fetcher, "JUR-822", attempts=1) is None


# ── Batch verification ──────────────────────────────────────────────

@pytest.mark.asyncio
async def test_reject_split_keeps_hers_and_local_cards_need_no_request():
    fetcher = _Fetcher({})  # any fetch would raise
    items = [
        _item("JUR-822", "Ichika"),                                     # hers
        _item("CJOD-256", "Ichika Matsumoto"),                           # namesake
    ]
    kept, rejected = await reject_misattributed(fetcher, STAR, items)

    assert [i.code for i in kept] == ["JUR-822"]
    assert rejected == [("CJOD-256", "other_star")]
    assert fetcher.calls == []


@pytest.mark.asyncio
async def test_reject_looks_up_linkless_codes_and_keeps_unknowns():
    rss = "https://ijavtorrent.com/?searchTerm=JUR-900"
    unknown = "https://ijavtorrent.com/?searchTerm=JUR-901"
    fetcher = _Fetcher({
        rss: _card("JUR-900", "Ichika Nagano"),   # belongs to a namesake
        unknown: _card("JUR-901"),                 # no actress links: unknown
    })
    items = [_item("JUR-900"), _item("JUR-901")]  # RSS-only: no actress links

    kept, rejected = await reject_misattributed(fetcher, STAR, items)

    assert [i.code for i in kept] == ["JUR-901"]
    assert rejected == [("JUR-900", "other_star")]
    assert len(fetcher.calls) == 2


@pytest.mark.asyncio
async def test_reject_keeps_everything_when_lookups_fail():
    fetcher = _Fetcher({
        "https://ijavtorrent.com/?searchTerm=JUR-900": TimeoutError("down"),
    })
    kept, rejected = await reject_misattributed(fetcher, STAR, [_item("JUR-900")])
    assert [i.code for i in kept] == ["JUR-900"]
    assert rejected == []


# ── Sync wiring ─────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_sync_helper_verifies_only_new_codes(monkeypatch):
    """Existing rows are never refetched — verification is a new-code cost."""
    from scrapers.v2.tasks import sync_titles as st

    async def _fake_reject(fetcher, star, items, **kwargs):
        assert [i.code for i in items] == ["NEW-001"]
        return [], [("NEW-001", "other_star")]

    monkeypatch.setattr(st, "reject_misattributed", _fake_reject)
    items = [_item("OLD-001", "Ichika"), _item("NEW-001")]
    out = await st._drop_misattributed(
        _Fetcher({}), STAR, items, existing_codes={(1, "OLD-001")}, star_id=1
    )
    assert [i.code for i in out] == ["OLD-001"]


@pytest.mark.asyncio
async def test_other_star_blacklist_never_expires(pg_test_db):
    """Attribution cannot change: the entry must survive the retry window."""
    from core import db

    pg_test_db.execute("INSERT INTO stars (id, name) VALUES (1, 'Ichika')")
    pg_test_db.execute(
        "INSERT INTO title_blacklist (star_id, code, reason, last_seen) VALUES"
        " (1, 'CJOD-256', 'other_star', now() - interval '400 days'),"
        " (1, 'NOCOVER-1', 'no_cover', now() - interval '400 days'),"
        " (1, 'FRESH-1', 'no_cover', now()),"
        " (1, 'DEAD-OLD', 'dead_magnet', now() - interval '40 days'),"
        " (1, 'DEAD-NEW', 'dead_magnet', now() - interval '2 days')"
    )
    blacklisted = db.load_blacklisted_codes(conn=pg_test_db)
    assert blacklisted == {(1, "CJOD-256"), (1, "FRESH-1"), (1, "DEAD-NEW")}
