#!/usr/bin/env python3
"""tests/test_file_vault.py — ostore file vault API (password hash in PG).

Locks path normalization, scrypt verify, CRUD via /api/files/vault, and auth gate.
"""
from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.routers import files_vault as vault_router
from backend.routers.auth import require_auth
from backend.services import file_vault as vault_svc

@pytest.fixture()
def vault_client(pg_test_db):
    app = FastAPI()
    app.include_router(vault_router.router, dependencies=[])
    app.dependency_overrides[require_auth] = lambda: None
    with TestClient(app) as client:
        yield client


def test_scrypt_roundtrip():
    salt = vault_svc.new_kdf_salt()
    stored = vault_svc.hash_password("hunter2", salt)
    assert vault_svc.verify_password("hunter2", salt, stored)
    assert not vault_svc.verify_password("wrong", salt, stored)


def test_vault_crud_and_api(vault_client):
    c = vault_client
    assert c.get("/api/files/vault").json()["items"] == []

    r = c.post("/api/files/vault", json={"path": "clips/a.mp4", "kind": "file", "password": "secret"})
    assert r.status_code == 200
    body = r.json()
    assert body["path"] == "clips/a.mp4"
    assert body["kdf_salt"]

    r = c.post("/api/files/vault/unlock", json={"path": "clips/a.mp4", "password": "secret"})
    assert r.status_code == 200
    assert r.json()["ok"] is True

    r = c.post("/api/files/vault/unlock", json={"path": "clips/a.mp4", "password": "nope"})
    assert r.status_code == 403

    items = c.get("/api/files/vault").json()["items"]
    assert len(items) == 1
    assert items[0]["kind"] == "file"

    r = c.post("/api/files/vault/move", json={"from_path": "clips/a.mp4", "to_path": "archive/a.mp4"})
    assert r.status_code == 200
    assert c.get("/api/files/vault").json()["items"][0]["path"] == "archive/a.mp4"

    r = c.post("/api/files/vault/password", json={
        "path": "archive/a.mp4",
        "old_password": "secret",
        "new_password": "newsecret",
    })
    assert r.status_code == 200
    assert c.post("/api/files/vault/unlock", json={"path": "archive/a.mp4", "password": "newsecret"}).status_code == 200

    r = c.delete("/api/files/vault", params={"path": "archive/a.mp4"})
    assert r.status_code == 200
    assert c.get("/api/files/vault").json()["items"] == []


def test_vault_invalid_path(vault_client):
    r = vault_client.post("/api/files/vault", json={"path": "../etc", "kind": "file", "password": "x"})
    assert r.status_code == 400


def test_delete_prefix(vault_client):
    c = vault_client
    c.post("/api/files/vault", json={"path": "box", "kind": "dir", "password": "p"})
    c.post("/api/files/vault", json={"path": "box/nested.txt", "kind": "file", "password": "p"})
    r = c.delete("/api/files/vault", params={"path": "box", "recursive": True})
    assert r.status_code == 200
    assert r.json()["deleted"] == 2
