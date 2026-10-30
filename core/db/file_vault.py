"""core/db/file_vault.py — Encrypted file/folder metadata (ostore paths)."""

from __future__ import annotations

from .connection import _conn
from .ops_log import trace_db


def _normalize_path(path: str) -> str:
    p = path.strip().strip("/")
    if not p or ".." in p.split("/") or path.startswith("/") or "\x00" in p:
        raise ValueError("invalid path")
    return p


@trace_db
def list_vault_paths(conn=None) -> list[dict]:
    should_close = conn is None
    conn = conn or _conn()
    try:
        rows = conn.execute(
            "SELECT path, kind, kdf_salt, created_at FROM file_vault ORDER BY path"
        ).fetchall()
        return [
            {"path": r[0], "kind": r[1], "kdf_salt": r[2], "created_at": r[3]}
            for r in rows
        ]
    finally:
        if should_close:
            conn.close()


@trace_db
def get_vault(path: str, conn=None) -> dict | None:
    path = _normalize_path(path)
    should_close = conn is None
    conn = conn or _conn()
    try:
        row = conn.execute(
            "SELECT path, kind, password_hash, kdf_salt, created_at FROM file_vault WHERE path = %s",
            (path,),
        ).fetchone()
        if not row:
            return None
        return {
            "path": row[0],
            "kind": row[1],
            "password_hash": row[2],
            "kdf_salt": row[3],
            "created_at": row[4],
        }
    finally:
        if should_close:
            conn.close()


@trace_db
def upsert_vault(path: str, kind: str, password_hash: str, kdf_salt: str, conn=None) -> None:
    path = _normalize_path(path)
    if kind not in ("file", "dir"):
        raise ValueError("invalid kind")
    should_close = conn is None
    conn = conn or _conn()
    try:
        conn.execute(
            """
            INSERT INTO file_vault (path, kind, password_hash, kdf_salt)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (path) DO UPDATE SET
                kind = EXCLUDED.kind,
                password_hash = EXCLUDED.password_hash,
                kdf_salt = EXCLUDED.kdf_salt,
                updated_at = CURRENT_TIMESTAMP
            """,
            (path, kind, password_hash, kdf_salt),
        )
    finally:
        if should_close:
            conn.close()


@trace_db
def delete_vault(path: str, conn=None) -> bool:
    path = _normalize_path(path)
    should_close = conn is None
    conn = conn or _conn()
    try:
        cur = conn.execute("DELETE FROM file_vault WHERE path = %s", (path,))
        return cur.rowcount > 0
    finally:
        if should_close:
            conn.close()


@trace_db
def delete_vault_prefix(prefix: str, conn=None) -> int:
    """Remove vault rows for `prefix` and everything under it."""
    prefix = _normalize_path(prefix)
    should_close = conn is None
    conn = conn or _conn()
    try:
        cur = conn.execute(
            "DELETE FROM file_vault WHERE path = %s OR path LIKE %s",
            (prefix, f"{prefix}/%"),
        )
        return cur.rowcount
    finally:
        if should_close:
            conn.close()


@trace_db
def move_vault(from_path: str, to_path: str, conn=None) -> int:
    from_path = _normalize_path(from_path)
    to_path = _normalize_path(to_path)
    should_close = conn is None
    conn = conn or _conn()
    try:
        rows = conn.execute(
            "SELECT path, kind, password_hash, kdf_salt FROM file_vault"
            " WHERE path = %s OR path LIKE %s",
            (from_path, f"{from_path}/%"),
        ).fetchall()
        if not rows:
            return 0
        n = 0
        for path, kind, ph, salt in rows:
            if path == from_path:
                new_path = to_path
            else:
                new_path = to_path + path[len(from_path) :]
            conn.execute(
                """
                INSERT INTO file_vault (path, kind, password_hash, kdf_salt)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (path) DO UPDATE SET
                    kind = EXCLUDED.kind,
                    password_hash = EXCLUDED.password_hash,
                    kdf_salt = EXCLUDED.kdf_salt,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (new_path, kind, ph, salt),
            )
            n += 1
        conn.execute(
            "DELETE FROM file_vault WHERE path = %s OR path LIKE %s",
            (from_path, f"{from_path}/%"),
        )
        return n
    finally:
        if should_close:
            conn.close()
