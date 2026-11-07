"""Telegram HTML fallback when tg-lint is unavailable."""

from __future__ import annotations

from typing import Any

from backend.services.notify.html_util import blockquote, esc, kv


def format_plain(event: str, data: dict[str, Any]) -> str:
    """Legacy plain text (tests / debugging)."""
    fn = _PLAIN.get(event)
    if fn is None:
        return f"xstream · {event}\n{_short_json(data)}"
    return fn(data)


def format_html(event: str, data: dict[str, Any]) -> str:
    fn = _HTML.get(event)
    if fn is None:
        return (
            "📡 <b>xstream</b>\n"
            f"{kv('Event', f'<code>{esc(event)}</code>')}\n"
            f"{blockquote(f'<pre>{esc(_short_json(data, 600))}</pre>')}"
        )
    return fn(data)


def _short_json(data: dict[str, Any], limit: int = 400) -> str:
    parts = []
    for k, v in data.items():
        s = str(v)
        if len(s) > 120:
            s = s[:117] + "..."
        parts.append(f"{k}={s}")
    out = " ".join(parts)
    return out if len(out) <= limit else out[: limit - 3] + "..."


def _sync_completed(d: dict[str, Any]) -> str:
    import os

    new = int(d.get("total_new") or 0)
    updated = int(d.get("total_updated") or 0)
    elapsed = d.get("elapsed", "?")
    trigger = esc(str(d.get("trigger") or "sync"))
    domain = os.environ.get("XSTREAM_DOMAIN") or "cc.guohuasun.com"

    stats = f"✨ <b>{new}</b> new"
    if updated > 0:
        stats += f" · <b>{updated}</b> updated"
    stats += f" · <i>{trigger} ({esc(str(elapsed))}s)</i>"

    header_lines = [
        "📚 <b>Library sync complete</b>",
        stats,
    ]

    failed = d.get("failed") or []
    if failed:
        names = ", ".join(esc(str(x)) for x in failed)
        header_lines.append(f"\n⚠️ <b>Failed stars:</b> <i>{names}</i>")

    cards: list[str] = ["\n".join(header_lines)]

    for block in d.get("star_updates") or []:
        name = esc(str(block.get("name") or "?"))
        code = str(block.get("code") or "")
        titles = block.get("new_titles") or []
        for t in titles:
            tc = esc(str(t.get("code") or "").strip())
            title = esc(str(t.get("title") or "").strip())
            date = str(t.get("date") or "").strip()
            res = str(t.get("resolution") or "").strip().strip("[]")
            size = str(t.get("size") or "").strip()
            magnet = str(t.get("magnet") or "").strip()
            cover_url = str(t.get("cover_url") or "").strip()

            cover_anchor = f'<a href="{esc(cover_url)}">&#8203;</a>' if cover_url else ""
            badges: list[str] = []
            if res:
                badges.append(f"🏷 <code>{esc(res)}</code>")
            if size:
                badges.append(f"💾 <code>{esc(size)}</code>")
            if date:
                badges.append(f"📅 <code>{esc(date)}</code>")

            star_label = f"⭐ <b>{name}</b>"
            if code:
                star_label += f" · <code>{esc(code)}</code>"

            card_parts = [
                f"{cover_anchor}{star_label} · 🎬 <b><code>{tc}</code></b>",
            ]
            if title and not title.lower() == tc.lower():
                card_parts.append(f'<i>"{title}"</i>')
            if badges:
                card_parts.append(" · ".join(badges))
            if magnet:
                card_parts.append(f"🧲 <code>{esc(magnet)}</code>")
            if domain and tc:
                card_parts.append(f'🔗 <a href="https://{domain}/#search={tc}">Open in xstream</a>')

            cards.append("\n".join(card_parts))

    if new == 0 and not d.get("star_updates"):
        log_lines = d.get("log_lines") or []
        if log_lines:
            tail = "<i>No structured updates; tail log:</i>\n" + "\n".join(
                f"  {esc(str(ln))}" for ln in log_lines[:8]
            )
            cards[0] += "\n" + blockquote(tail, expandable=False)

    return "\n\n===SPLIT===\n\n".join(cards) + "\n"


def _metrics_alert(d: dict[str, Any]) -> str:
    kind = str(d.get("kind") or "alert")
    headline = {"play_timeout": "Play timeout", "play_error": "Play error"}.get(kind, kind)
    detail = esc(str(d.get("detail") or ""))
    work = esc(str(d.get("code") or "-"))
    star = esc(str(d.get("star_code") or "-"))
    return (
        f"📉 <b>Metrics · {esc(headline)}</b>\n\n"
        f"{kv('Work', f'<code>{work}</code>')}\n"
        f"{kv('Star', f'<code>{star}</code>')}\n\n"
        f"{blockquote(f'<pre>{detail}</pre>', expandable=detail.count(chr(10)) > 4)}"
    )


def _sync_error(d: dict[str, Any]) -> str:
    trigger = esc(str(d.get("trigger") or "?"))
    err = esc(str(d.get("error") or ""))
    return (
        "⛔ <b>Sync failed</b>\n\n"
        f"{kv('Trigger', f'<code>{trigger}</code>')}\n\n"
        f"{blockquote(f'<pre>{err}</pre>')}"
    )


def _mag_completed(d: dict[str, Any]) -> str:
    scope = esc(str(d.get("scope") or "?"))
    alive = d.get("alive")
    dead = d.get("dead")
    swapped = d.get("swapped")
    elapsed = esc(str(d.get("elapsed") or "?"))
    return (
        "🧲 <b>Magnet check complete</b>\n\n"
        f"{kv('Scope', f'<code>{scope}</code>')}\n"
        f"{kv('Alive', f'<b>{alive}</b>')} · "
        f"{kv('Dead', str(dead))} · "
        f"{kv('Swapped', str(swapped))}\n"
        f"<i>{elapsed}s</i>"
    )


_PLAIN: dict[str, Any] = {
    "sync.completed": lambda d: _strip_tags(format_html("sync.completed", d)),
    "sync.error": lambda d: _strip_tags(format_html("sync.error", d)),
    "metrics.alert": lambda d: _strip_tags(format_html("metrics.alert", d)),
    "magnets.check_completed": lambda d: _strip_tags(format_html("magnets.check_completed", d)),
}


def _strip_tags(html_text: str) -> str:
    import re

    text = re.sub(r"<[^>]+>", "", html_text)
    return text.replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")


_HTML: dict[str, Any] = {
    "sync.completed": _sync_completed,
    "sync.error": _sync_error,
    "metrics.alert": _metrics_alert,
    "magnets.check_completed": _mag_completed,
}
