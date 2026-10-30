"""Telegram delivery — split long HTML/plain messages, never log secrets."""

from __future__ import annotations

import os
from typing import Any

import httpx

from core.logger import get_logger

log = get_logger("notify")

_TELEGRAM_API = "https://api.telegram.org/bot{token}/sendMessage"
_SEND_TIMEOUT = 15.0
_MAX_LEN = 4096


def _credentials() -> tuple[str, str]:
    token = (
        os.environ.get("XSTREAM_TELEGRAM_BOT_TOKEN")
        or os.environ.get("TELEGRAM_BOT_TOKEN")
        or ""
    ).strip()
    chat_id = (
        os.environ.get("XSTREAM_TELEGRAM_CHAT_ID")
        or os.environ.get("TELEGRAM_CHAT_ID")
        or ""
    ).strip()
    return token, chat_id


def telegram_configured() -> bool:
    token, chat_id = _credentials()
    return bool(token and chat_id)


async def send_messages(chunks: list[str], *, parse_mode: str | None) -> None:
    token, chat_id = _credentials()
    if not token or not chat_id:
        log.warning("telegram notify skipped: token or chat_id missing")
        return
    url = _TELEGRAM_API.format(token=token)
    async with httpx.AsyncClient(timeout=_SEND_TIMEOUT) as client:
        for text in chunks:
            ok = await _send_one(client, url, chat_id, text[:_MAX_LEN], parse_mode)
            if ok:
                continue
            if parse_mode == "HTML":
                plain = _strip_html(text[:_MAX_LEN])
                if plain and await _send_one(client, url, chat_id, plain, None):
                    log.warning("telegram HTML parse failed; sent plain fallback chunk")
                    continue
            return


async def _send_one(
    client: httpx.AsyncClient,
    url: str,
    chat_id: str,
    text: str,
    parse_mode: str | None,
) -> bool:
    payload: dict[str, Any] = {
        "chat_id": chat_id,
        "text": text,
        "disable_web_page_preview": True,
    }
    if parse_mode:
        payload["parse_mode"] = parse_mode
    r = await client.post(url, json=payload)
    if r.status_code != 200:
        log.warning(f"telegram sendMessage HTTP {r.status_code}: {r.text[:200]}")
        return False
    body = r.json()
    if not body.get("ok"):
        log.warning(f"telegram sendMessage rejected: {str(body)[:300]}")
        return False
    return True


def _strip_html(text: str) -> str:
    import re

    out = re.sub(r"<[^>]+>", "", text)
    return out.replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")


def split_message(text: str, max_len: int = _MAX_LEN, *, parse_mode: str | None = None) -> list[str]:
    if len(text) <= max_len:
        return [text]
    chunks: list[str] = []
    rest = text
    while rest:
        if len(rest) <= max_len:
            chunks.append(rest)
            break
        window = rest[:max_len]
        cut = window.rfind("\n\n")
        if cut < max_len // 4:
            cut = window.rfind("\n")
        if cut < max_len // 4:
            cut = max_len
        piece = rest[:cut].rstrip()
        if parse_mode == "HTML":
            piece = _close_dangling_html(piece)
        chunks.append(piece)
        rest = rest[cut:].lstrip()
    return chunks


def _close_dangling_html(text: str) -> str:
    """Best-effort close tags when splitting long HTML (avoid broken parse_mode)."""
    for tag in ("blockquote", "pre", "i", "b", "code"):
        open_tag = f"<{tag}"
        close_tag = f"</{tag}>"
        opens = text.count(open_tag)
        closes = text.count(close_tag)
        if opens > closes:
            text += close_tag * (opens - closes)
    return text
