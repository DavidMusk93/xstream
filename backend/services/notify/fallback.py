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
    new = int(d.get("total_new") or 0)
    updated = int(d.get("total_updated") or 0)
    elapsed = d.get("elapsed", "?")
    trigger = esc(str(d.get("trigger") or "sync"))
    lines = [
        "📚 <b>Library sync complete</b>\n",
        f"{kv('New', f'<b>{new}</b>')} · {kv('Updated', f'<b>{updated}</b>')}",
        f"<i>{trigger} · {esc(str(elapsed))}s</i>",
    ]
    for block in d.get("star_updates") or []:
        name = esc(str(block.get("name") or "?"))
        code = str(block.get("code") or "")
        count = int(block.get("count") or 0)
        head = f"\n⭐ <b>{name}</b>"
        if code:
            head += f" · <code>{esc(code)}</code>"
        head += f"\n<b>{count}</b> new title(s)"
        titles = block.get("new_titles") or []
        body_parts: list[str] = []
        for t in titles:
            tc = esc(str(t.get("code") or ""))
            title = esc(str(t.get("title") or ""))
            meta = " · ".join(
                x
                for x in (
                    str(t.get("date") or ""),
                    str(t.get("resolution") or ""),
                    str(t.get("size") or ""),
                )
                if x
            )
            part = f"• <code>{tc}</code>"
            if title:
                part += f"\n  {title}"
            if meta:
                part += f"\n  <i>{esc(meta)}</i>"
            body_parts.append(part)
        if body_parts:
            head += "\n" + blockquote("\n".join(body_parts), expandable=len(body_parts) > 3)
        lines.append(head)
    failed = d.get("failed") or []
    if failed:
        names = ", ".join(esc(str(x)) for x in failed)
        lines.append(f"\n⚠️ {kv('Failed stars', f'<i>{names}</i>')}")
    return "\n".join(lines) + "\n"


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
