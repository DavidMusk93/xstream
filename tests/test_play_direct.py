#!/usr/bin/env python3
"""tests/test_play_direct.py — ad-hoc magnet play + files config regression tests.

Locks:
- gc_orphaned_torrents preserves a cache dir carrying a `.adhoc` marker while
  still deleting an unmarked orphan (ad-hoc torrents are never in titles, so
  without the marker the GC would wipe them).
- TorrentEngine.mark_adhoc writes the marker and flags the info dict.
- POST /api/play/direct: 400 on invalid magnet, 401 without the auth cookie;
  the happy path marks adhoc and kicks off the head download.
- GET /api/play/recent lists only `.adhoc` dirs, newest first.
- DELETE /api/play/{hash} removes the cache and 404s without the marker.
- GET /api/files/config: 503 without OSTORE_TOKEN, config payload with it.

The GC test builds a real TorrentEngine on a tmp cache dir and uses the
shared pg_test_db fixture, so it skips cleanly when xstream_test PG is
unavailable. Router tests stub app.state.engine — no libtorrent, DB, seed,
or network needed.
"""
from __future__ import annotations

import os
import shutil
import threading

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.routers import play as play_router
from backend.routers.auth import require_auth
from backend.services.magnet_checker import extract_hash
from backend.services.torrent_engine import ADHOC_MARKER, TorrentEngine

GOOD_HASH = "ab" * 20
GOOD_MAGNET = f"magnet:?xt=urn:btih:{GOOD_HASH}&dn=My%20Video"


# ── Engine-level tests ──────────────────────────────────

@pytest.fixture()
def engine_tmp(tmp_path):
    """A real TorrentEngine on a throwaway cache dir (no seed, no network)."""
    engine = TorrentEngine(str(tmp_path / "cache"), max_size_gb=1)
    yield engine
    engine.shutdown()


def test_mark_adhoc_and_gc_protection(engine_tmp, pg_test_db):
    engine = engine_tmp
    # Two orphan dirs on disk: one ad-hoc, one plain. titles is empty, so
    # both are orphans from the GC's point of view.
    adhoc_hash = "a" * 40
    plain_hash = "b" * 40
    adhoc_dir = os.path.join(engine.cache_dir, adhoc_hash)
    plain_dir = os.path.join(engine.cache_dir, plain_hash)
    os.makedirs(adhoc_dir)
    os.makedirs(plain_dir)

    # mark_adhoc requires the torrent to be loaded; fake a minimal info dict.
    with engine.lock:
        engine.torrents[adhoc_hash] = {"hash": adhoc_hash}
    assert engine.mark_adhoc(adhoc_hash) is True
    assert os.path.exists(os.path.join(adhoc_dir, ADHOC_MARKER))
    assert engine.torrents[adhoc_hash]["adhoc"] is True
    assert engine.mark_adhoc("c" * 40) is False  # unknown hash

    removed = engine.gc_orphaned_torrents()
    assert removed == 1
    assert os.path.isdir(adhoc_dir)  # marker protects it
    assert not os.path.isdir(plain_dir)


# ── Router-level tests ──────────────────────────────────

class _FakeEngine:
    """Minimal engine stub for router-level tests (no libtorrent)."""

    def __init__(self, cache_dir: str):
        self.cache_dir = cache_dir
        self.torrents: dict[str, dict] = {}
        self.lock = threading.Lock()
        self.marked: list[str] = []
        self.resumed: list[tuple] = []

    def add_torrent(self, magnet: str, prefetch: bool = False):
        hash_str = extract_hash(magnet)
        if not hash_str:
            return None
        info = {"hash": hash_str, "magnet": magnet, "adhoc": False}
        with self.lock:
            self.torrents[hash_str] = info
        os.makedirs(os.path.join(self.cache_dir, hash_str), exist_ok=True)
        return info

    def mark_adhoc(self, hash_str: str) -> bool:
        with self.lock:
            info = self.torrents.get(hash_str)
            if not info:
                return False
            info["adhoc"] = True
        self.marked.append(hash_str)
        open(os.path.join(self.cache_dir, hash_str, ADHOC_MARKER), "w").close()
        return True

    def resume_download(self, hash_str: str, time_sec: float, duration_sec: float) -> bool:
        self.resumed.append((hash_str, time_sec, duration_sec))
        return True

    def get_status(self, hash_str: str):
        if hash_str not in self.torrents:
            return None
        return {"ready": False, "peers": 0, "progress": 0.0}

    def remove_torrent(self, hash_str: str) -> bool:
        with self.lock:
            if hash_str not in self.torrents:
                return False
            self.torrents.pop(hash_str)
        shutil.rmtree(os.path.join(self.cache_dir, hash_str), ignore_errors=True)
        return True


@pytest.fixture()
def engine_stub(tmp_path):
    return _FakeEngine(str(tmp_path / "cache"))


@pytest.fixture()
def client(engine_stub):
    app = FastAPI()
    app.dependency_overrides[require_auth] = lambda: None
    app.state.engine = engine_stub
    app.include_router(play_router.router)
    app.include_router(play_router.files_router)
    return TestClient(app)


def test_play_direct_invalid_magnet(client):
    res = client.post("/api/play/direct", json={"magnet": "not-a-magnet"})
    assert res.status_code == 400
    assert res.json()["detail"] == "Invalid magnet"


def test_play_direct_requires_auth(engine_stub):
    app = FastAPI()  # no require_auth override -> cookie enforced
    app.state.engine = engine_stub
    app.include_router(play_router.router)
    res = TestClient(app).post("/api/play/direct", json={"magnet": GOOD_MAGNET})
    assert res.status_code == 401


def test_play_direct_happy_path(client, engine_stub):
    res = client.post("/api/play/direct", json={"magnet": GOOD_MAGNET})
    assert res.status_code == 200
    data = res.json()
    assert data["hash"] == GOOD_HASH
    assert data["name"] == "My Video"  # dn= parsed and unquoted
    assert data["status"] == "added"
    assert data["ready"] is False
    # Marker on disk + in-memory flag, and head download kicked off.
    assert os.path.exists(os.path.join(engine_stub.cache_dir, GOOD_HASH, ADHOC_MARKER))
    assert engine_stub.torrents[GOOD_HASH]["adhoc"] is True
    assert engine_stub.resumed == [(GOOD_HASH, 0, 0)]


def test_play_direct_idempotent_readd(client, engine_stub):
    for _ in range(2):
        res = client.post("/api/play/direct", json={"magnet": GOOD_MAGNET})
        assert res.status_code == 200
    assert len(engine_stub.torrents) == 1


def test_play_recent_lists_only_adhoc_dirs(client, engine_stub):
    # One ad-hoc dir (via the endpoint), one plain dir without the marker.
    client.post("/api/play/direct", json={"magnet": GOOD_MAGNET})
    plain = os.path.join(engine_stub.cache_dir, "cd" * 20)
    os.makedirs(plain)
    with open(os.path.join(plain, "junk.bin"), "wb") as f:
        f.write(b"\x00" * 1024)

    res = client.get("/api/play/recent")
    assert res.status_code == 200
    items = res.json()["items"]
    assert [i["hash"] for i in items] == [GOOD_HASH]
    assert items[0]["name"] == "My Video"  # from the magnet dn
    assert items[0]["size_on_disk"] >= 0
    assert items[0]["mtime"] > 0


def test_play_delete_removes_adhoc_cache(client, engine_stub):
    client.post("/api/play/direct", json={"magnet": GOOD_MAGNET})
    res = client.delete(f"/api/play/{GOOD_HASH}")
    assert res.status_code == 200
    assert res.json() == {"ok": True}
    assert not os.path.exists(os.path.join(engine_stub.cache_dir, GOOD_HASH))
    # Second delete: marker dir is gone -> 404.
    assert client.delete(f"/api/play/{GOOD_HASH}").status_code == 404


def test_play_delete_rejects_non_adhoc_dir(client, engine_stub):
    # A cache dir without the marker is not an ad-hoc play; refuse to delete.
    plain_hash = "cd" * 20
    os.makedirs(os.path.join(engine_stub.cache_dir, plain_hash))
    assert client.delete(f"/api/play/{plain_hash}").status_code == 404


def test_files_config_requires_token(client, monkeypatch):
    monkeypatch.delenv("OSTORE_TOKEN", raising=False)
    res = client.get("/api/files/config")
    assert res.status_code == 503
    assert res.json()["detail"] == "ostore not configured"


def test_files_config_returns_base_and_token(client, monkeypatch):
    monkeypatch.setenv("OSTORE_TOKEN", "secret-token")
    monkeypatch.delenv("OSTORE_PUBLIC_BASE", raising=False)
    res = client.get("/api/files/config")
    assert res.status_code == 200
    assert res.json() == {"base_url": "/ostore", "token": "secret-token"}

    monkeypatch.setenv("OSTORE_PUBLIC_BASE", "https://files.example.com/ostore")
    res = client.get("/api/files/config")
    assert res.json()["base_url"] == "https://files.example.com/ostore"
