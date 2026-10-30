"""Minimal Telegram HTML helpers (Bot API HTML mode)."""

from __future__ import annotations

import html


def esc(s: str) -> str:
    return html.escape(s, quote=False)


def kv(label: str, value: str) -> str:
    if not value:
        return ""
    return f"<b>{esc(label)}:</b> {value}"


def blockquote(body: str, *, expandable: bool = False) -> str:
    if not body.strip():
        return ""
    if expandable:
        return f"<blockquote expandable>{body}</blockquote>\n"
    return f"<blockquote>{body}</blockquote>\n"
