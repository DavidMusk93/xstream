"""Unit tests for backend/services/bt_client.py delegation helpers."""
from __future__ import annotations

import pytest

from backend.services import bt_client


def test_bt_client_disabled_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("XSTREAM_BT_URL", raising=False)
    assert bt_client.get_base_url() is None
    assert bt_client.is_enabled() is False


def test_bt_client_enabled_strips_trailing_slash(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("XSTREAM_BT_URL", " http://127.0.0.1:8766/ ")
    assert bt_client.get_base_url() == "http://127.0.0.1:8766"
    assert bt_client.is_enabled() is True
