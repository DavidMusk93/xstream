"""Build a self-contained X inject brief for external agents.

Agents call GET /api/social/x/agent-brief once (authenticated) and receive
the work queue, JSON schemas, and a copy-paste prompt — no repo docs required.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

def _parse_checked(iso: str | None) -> datetime | None:
    if not iso:
        return None
    try:
        dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
        if dt.tzinfo:
            return dt.astimezone(UTC).replace(tzinfo=None)
        return dt
    except ValueError:
        return None


def build_x_agent_brief(
    *,
    origin: str,
    star_rows: list[tuple],
    creators: list[dict[str, Any]],
    stale_hours: int = 72,
    inject_help: dict[str, Any],
    creator_help: dict[str, Any],
) -> dict[str, Any]:
    """Assemble machine + human brief from DB snapshots (read on the caller side)."""
    origin = origin.rstrip("/")
    cutoff = datetime.now(UTC).replace(tzinfo=None) - timedelta(hours=stale_hours)

    stars_pending: list[dict[str, Any]] = []
    for code, name, jp, handle, checked_at, post_count in star_rows:
        checked = checked_at
        stale = checked is None or checked < cutoff
        stars_pending.append({
            "star": code,
            "name": name,
            "jp": jp or "",
            "handle": handle,
            "checked_at": checked.isoformat() + "Z" if checked else None,
            "post_count": post_count,
            "needs_check": stale,
        })
    stars_todo = [s for s in stars_pending if s["needs_check"]]

    creators_detail: list[dict[str, Any]] = []
    creators_stale: list[str] = []
    for c in creators:
        handle = c.get("handle") or ""
        posts = c.get("posts") or []
        checked = _parse_checked(c.get("checked_at"))
        needs_en = any(not (p.get("en") or "").strip() for p in posts)
        stale = checked is None or checked < cutoff
        entry = {
            "handle": handle,
            "name": c.get("name") or "",
            "post_count": len(posts),
            "checked_at": c.get("checked_at"),
            "needs_refresh": stale or needs_en,
            "needs_en": needs_en,
        }
        creators_detail.append(entry)
        if entry["needs_refresh"]:
            creators_stale.append(handle)

    prompt = _prompt_markdown(
        origin=origin,
        stale_hours=stale_hours,
        stars_todo=stars_todo,
        creators_detail=creators_detail,
        creators_stale=creators_stale,
    )

    return {
        "version": 1,
        "origin": origin,
        "stale_hours": stale_hours,
        "auth": {
            "type": "cookie",
            "cookie_name": "xstream_auth",
            "login": f"POST {origin}/api/auth",
            "login_body": {"password": "<daily password — ask owner, never log it>"},
            "note": "After login, send Cookie: xstream_auth=ok on every inject call.",
        },
        "endpoints": {
            "agent_brief": f"GET {origin}/api/social/x/agent-brief",
            "stars_pending": f"GET {origin}/api/social/x/pending?stale_hours={stale_hours}",
            "stars_inject": f"POST {origin}/api/social/x",
            "creators_list": f"GET {origin}/api/social/x/creators",
            "creators_inject": f"POST {origin}/api/social/x/creators",
        },
        "work_queue": {
            "stars_needing_check": len(stars_todo),
            "stars": stars_todo,
            "creators_stale": creators_stale,
            "creators": creators_detail,
            "discover_creators_hint": (
                "Browse the owner's X Following feed; inject any account that is "
                "NOT a library star via POST /api/social/x/creators (10 posts each)."
            ),
        },
        "schemas": {
            "stars": inject_help,
            "creators": creator_help,
        },
        "prompt_markdown": prompt,
    }


def _prompt_markdown(
    *,
    origin: str,
    stale_hours: int,
    stars_todo: list[dict[str, Any]],
    creators_detail: list[dict[str, Any]],
    creators_stale: list[str],
) -> str:
    star_lines = [
        f"- {s['star']}: {s['name']}"
        + (f" / {s['jp']}" if s.get('jp') and s['jp'] != s['name'] else "")
        + (f" — known @{s['handle']}" if s.get('handle') else "")
        for s in stars_todo[:80]
    ]
    if len(stars_todo) > 80:
        star_lines.append(f"- … and {len(stars_todo) - 80} more (see work_queue.stars)")

    creator_lines = [
        f"- @{c['handle']}: {c['name'] or c['handle']}"
        + (" · needs en" if c.get("needs_en") else "")
        + (" · stale" if c["handle"] in creators_stale else "")
        for c in creators_detail[:40]
    ]

    return "\n".join([
        "# xstream X inject (agent runbook)",
        "",
        "You update a private app that **never calls the X API**. Browse x.com as the logged-in owner, then POST JSON to xstream.",
        "",
        "## Auth",
        f"1. `POST {origin}/api/auth` with JSON `{{\"password\":\"…\"}}` (owner provides daily password).",
        "2. Reuse `Cookie: xstream_auth=ok` on all requests below.",
        "",
        "## Refresh this brief anytime",
        f"`GET {origin}/api/social/x/agent-brief?stale_hours={stale_hours}`",
        "",
        "## A) Library stars (actresses) — newest **5** posts each",
        f"`POST {origin}/api/social/x` body: `{{\"star\": \"<code|null>\", \"content\": <JSON|string>}}`",
        "Batch shape: `{\"stars\":[{\"star\":\"CODE\",\"handle\":\"…\",\"posts\":[…]}]}`",
        "No account: `{\"handle\": null}` or text `none`.",
        "",
        f"Stars needing a check (>{stale_hours}h or never): **{len(stars_todo)}**",
        *(star_lines or ["- (none — spot-check stale entries in work_queue)"]),
        "",
        "## B) Body creators (owner's follows, NOT library stars) — newest **10** posts each",
        f"`POST {origin}/api/social/x/creators` body: `{{\"content\": {{\"creators\":[…]}}}}`",
        "Also browse **Following** for new handles not listed below.",
        "",
        f"Known creators: **{len(creators_detail)}** · stale/en queue: **{len(creators_stale)}**",
        *(creator_lines or ["- (none yet — inject from Following feed)"]),
        "",
        "## Post fields (both stars and creators)",
        "- `url`, `text` (verbatim), optional `posted_at` (ISO-8601 UTC)",
        "- `media`: only `https://pbs.twimg.com/…`",
        "- `en`: concise, cute, flirty English for UI cards (you write it; keep emoji/#tags)",
        "- `{url, en}` only = translation patch for an existing post",
        "",
        "## Reply",
        "POST the JSON yourself (do not only print it). Confirm with GET pending/creators.",
        "",
        "Example creators batch:",
        "```json",
        '{"creators":[{"handle":"user","name":"Name","avatar":"https://pbs.twimg.com/profile_images/…/photo.jpg",',
        '"posts":[{"url":"https://x.com/user/status/1","text":"…","en":"…","media":[]}]}]}',
        "```",
    ])
