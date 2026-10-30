"""backend/services/file_vault.py — Password hashing for file vault (stdlib scrypt)."""

from __future__ import annotations

import base64
import hashlib
import hmac
import os
import secrets

_SCRYPT_N = 2**14
_SCRYPT_R = 8
_SCRYPT_P = 1
_SCRYPT_DKLEN = 32


def new_kdf_salt() -> str:
    return base64.urlsafe_b64encode(secrets.token_bytes(16)).decode("ascii").rstrip("=")


def hash_password(password: str, kdf_salt: str) -> str:
    """Derive a stored verifier from password + per-path salt (not the AES KDF salt alone)."""
    pepper = kdf_salt.encode("utf-8")
    raw = hashlib.scrypt(
        password.encode("utf-8"),
        salt=pepper,
        n=_SCRYPT_N,
        r=_SCRYPT_R,
        p=_SCRYPT_P,
        dklen=_SCRYPT_DKLEN,
    )
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def verify_password(password: str, kdf_salt: str, stored: str) -> bool:
    try:
        expect = base64.urlsafe_b64decode(stored + "==")
    except Exception:
        return False
    got = hashlib.scrypt(
        password.encode("utf-8"),
        salt=kdf_salt.encode("utf-8"),
        n=_SCRYPT_N,
        r=_SCRYPT_R,
        p=_SCRYPT_P,
        dklen=_SCRYPT_DKLEN,
    )
    return hmac.compare_digest(got, expect)
