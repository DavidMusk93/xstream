"""Render notify payloads — prefer tg-lint (HTML), else plain fallback."""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from typing import Any

from backend.services.notify.fallback import format_html
from core.logger import get_logger

log = get_logger("notify")

_TG_LINT_TIMEOUT = 8.0
_REPO_LINT = Path(__file__).resolve().parents[3] / "tools" / "tg-lint" / "target" / "release" / "tg-lint"


def tg_lint_path() -> Path | None:
    raw = (os.environ.get("XSTREAM_TG_LINT") or "").strip()
    if raw:
        p = Path(raw)
        return p if p.is_file() else None
    return _REPO_LINT if _REPO_LINT.is_file() else None


async def render(event: str, data: dict[str, Any]) -> tuple[str, str | None]:
    """Return (message text, telegram parse_mode or None for plain)."""
    lint = tg_lint_path()
    if lint is not None:
        try:
            text = await _run_tg_lint(lint, event, data)
            if text:
                return text, "HTML"
        except Exception:
            log.exception("tg-lint failed; using plain fallback")
    return format_html(event, data), "HTML"


async def _run_tg_lint(binary: Path, event: str, data: dict[str, Any]) -> str:
    payload = json.dumps({"event": event, "data": data}, ensure_ascii=False).encode("utf-8")
    proc = await asyncio.create_subprocess_exec(
        str(binary),
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await asyncio.wait_for(
        proc.communicate(payload),
        timeout=_TG_LINT_TIMEOUT,
    )
    if proc.returncode != 0:
        err = (stderr or b"").decode("utf-8", errors="replace")[:300]
        raise RuntimeError(f"tg-lint exit {proc.returncode}: {err}")
    return (stdout or b"").decode("utf-8", errors="replace")
