"""Telegram delivery — split long HTML/plain messages, classify errors, never log secrets."""

from __future__ import annotations

import asyncio
import os
import re
from dataclasses import dataclass
from typing import Any

import httpx

from core.logger import get_logger

log = get_logger("notify")

_TELEGRAM_API = "https://api.telegram.org/bot{token}/sendMessage"
_SEND_TIMEOUT = 15.0
_MAX_LEN = 4096
_DEFAULT_CHUNK_INTERVAL = 1.05  # Safe pacing for single-chat Telegram flood control
_COVER_ANCHOR_RE = re.compile(r'<a\s+href="([^"]+)"[^>]*>&#8203;</a>')
_HTML_TAG_RE = re.compile(r"<[^>]+>")


@dataclass(frozen=True, slots=True)
class TelegramDeliveryOutcome:
    """Structured result of sending a single Telegram chunk."""

    ok: bool
    retryable: bool = False
    retry_after: float | None = None
    error: str = ""


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


def _build_payload(chat_id: str, text: str, parse_mode: str | None) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "chat_id": chat_id,
        "text": text,
    }
    if parse_mode:
        payload["parse_mode"] = parse_mode

    m = _COVER_ANCHOR_RE.search(text)
    if m:
        payload["link_preview_options"] = {
            "is_disabled": False,
            "url": m.group(1),
            "prefer_large_media": True,
            "show_above_text": True,
        }
    else:
        payload["link_preview_options"] = {"is_disabled": True}
        payload["disable_web_page_preview"] = True
    return payload


async def _post_once(
    client: httpx.AsyncClient,
    url: str,
    chat_id: str,
    text: str,
    parse_mode: str | None,
) -> tuple[TelegramDeliveryOutcome, bool]:
    """Send one HTTP request; returns (outcome, is_html_parse_error)."""
    payload = _build_payload(chat_id, text, parse_mode)
    try:
        r = await client.post(url, json=payload)
    except (httpx.TimeoutException, httpx.NetworkError, httpx.RemoteProtocolError) as exc:
        err = f"{type(exc).__name__}: {exc}"
        log.warning(f"telegram sendMessage transient error: {err}")
        return TelegramDeliveryOutcome(ok=False, retryable=True, error=err), False
    except httpx.HTTPError as exc:
        err = f"{type(exc).__name__}: {exc}"
        log.warning(f"telegram sendMessage HTTP error: {err}")
        return TelegramDeliveryOutcome(ok=False, retryable=True, error=err), False

    body: dict[str, Any] = {}
    try:
        parsed = r.json()
        if isinstance(parsed, dict):
            body = parsed
    except Exception:
        body = {}

    if r.status_code == 200 and body.get("ok"):
        return TelegramDeliveryOutcome(ok=True), False

    desc = str(body.get("description") or r.text[:200])

    if r.status_code == 429:
        raw_ra = (body.get("parameters") or {}).get("retry_after")
        try:
            retry_after = max(1.0, float(raw_ra))
        except (TypeError, ValueError):
            retry_after = 5.0
        err = f"HTTP 429 rate limited (retry_after={retry_after:.1f}s): {desc}"
        log.warning(f"telegram sendMessage {err}")
        return (
            TelegramDeliveryOutcome(ok=False, retryable=True, retry_after=retry_after, error=err),
            False,
        )

    if r.status_code >= 500:
        err = f"HTTP {r.status_code}: {desc}"
        log.warning(f"telegram sendMessage server error: {err}")
        return TelegramDeliveryOutcome(ok=False, retryable=True, error=err), False

    is_html_err = (
        r.status_code == 400
        and parse_mode == "HTML"
        and "parse" in desc.lower()
    )
    err = f"HTTP {r.status_code}: {desc}"
    log.warning(f"telegram sendMessage rejected: {err}")
    return TelegramDeliveryOutcome(ok=False, retryable=False, error=err), is_html_err


async def send_chunk(
    client: httpx.AsyncClient,
    text: str,
    *,
    parse_mode: str | None,
) -> TelegramDeliveryOutcome:
    """Deliver a single chunk with automatic HTML->plain fallback on entity parse errors."""
    token, chat_id = _credentials()
    if not token or not chat_id:
        log.warning("telegram notify skipped: token or chat_id missing")
        return TelegramDeliveryOutcome(ok=False, retryable=False, error="telegram credentials missing")

    url = _TELEGRAM_API.format(token=token)
    clipped = text[:_MAX_LEN]
    outcome, is_html_err = await _post_once(client, url, chat_id, clipped, parse_mode)
    if outcome.ok:
        return outcome

    if is_html_err:
        plain = _strip_html(clipped)
        if plain:
            fallback_outcome, _ = await _post_once(client, url, chat_id, plain, None)
            if fallback_outcome.ok:
                log.warning("telegram HTML parse failed; sent plain fallback chunk")
                return fallback_outcome
            return fallback_outcome

    return outcome


async def send_messages(
    chunks: list[str],
    *,
    parse_mode: str | None,
    chunk_interval: float = _DEFAULT_CHUNK_INTERVAL,
) -> None:
    """Direct delivery helper (used by /api/notify/test and standalone fallback)."""
    token, chat_id = _credentials()
    if not token or not chat_id:
        log.warning("telegram notify skipped: token or chat_id missing")
        return
    async with httpx.AsyncClient(timeout=_SEND_TIMEOUT) as client:
        for i, text in enumerate(chunks):
            if i > 0 and chunk_interval > 0:
                await asyncio.sleep(chunk_interval)
            outcome = await send_chunk(client, text, parse_mode=parse_mode)
            if not outcome.ok:
                raise RuntimeError(f"telegram send failed on chunk {i + 1}/{len(chunks)}: {outcome.error}")


def _strip_html(text: str) -> str:
    out = _HTML_TAG_RE.sub("", text)
    return out.replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")


def split_message(text: str, max_len: int = _MAX_LEN, *, parse_mode: str | None = None) -> list[str]:
    if "===SPLIT===" in text:
        parts = [p.strip() for p in text.split("===SPLIT===") if p.strip()]
        chunks: list[str] = []
        for part in parts:
            chunks.extend(_split_chunk(part, max_len, parse_mode=parse_mode))
        return chunks
    return _split_chunk(text, max_len, parse_mode=parse_mode)


def _split_chunk(text: str, max_len: int = _MAX_LEN, *, parse_mode: str | None = None) -> list[str]:
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
        # Never slice in the middle of an HTML tag like <a href="...">
        if parse_mode == "HTML":
            last_lt = rest.rfind("<", 0, cut)
            last_gt = rest.rfind(">", 0, cut)
            if last_lt > last_gt and last_lt > 0:
                cut = last_lt
        piece = rest[:cut].rstrip()
        if parse_mode == "HTML":
            piece = _close_dangling_html(piece)
        chunks.append(piece)
        rest = rest[cut:].lstrip()
    return chunks


def _close_dangling_html(text: str) -> str:
    """Best-effort close tags when splitting long HTML (avoid broken parse_mode)."""
    for tag in ("a", "blockquote", "pre", "i", "b", "code"):
        opens = len(re.findall(rf"<{tag}(?:\s|>)", text))
        closes = text.count(f"</{tag}>")
        if opens > closes:
            text += f"</{tag}>" * (opens - closes)
    return text
