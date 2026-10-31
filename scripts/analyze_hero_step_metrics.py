#!/usr/bin/env python3
"""Summarize hero_step client metrics from user_events.

Hero swipe paint time is recorded by the frontend as event ``hero_step`` with
meta JSON: ``paint_ms``, ``cache_hit``, ``src_tier`` (mid/thumb/full/api).

Usage (production DSN):
  set -a; . /etc/xstream.env; set +a
  uv run python scripts/analyze_hero_step_metrics.py
  uv run python scripts/analyze_hero_step_metrics.py --days 14
"""

from __future__ import annotations

import argparse
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from core.db.connection import _conn


def _pct(sorted_vals: list[int], p: float) -> int:
    if not sorted_vals:
        return 0
    idx = min(len(sorted_vals) - 1, max(0, int(len(sorted_vals) * p) - 1))
    return sorted_vals[idx]


def main() -> int:
    parser = argparse.ArgumentParser(description="Hero step paint metrics")
    parser.add_argument("--days", type=int, default=7, help="Lookback window")
    args = parser.parse_args()

    if not os.environ.get("XSTREAM_PG_DSN"):
        print("XSTREAM_PG_DSN not set", file=sys.stderr)
        return 1

    conn = _conn()
    try:
        rows = conn.execute(
            """
            SELECT meta
            FROM user_events
            WHERE event = 'hero_step'
              AND ts >= now() - make_interval(days => %s)
            ORDER BY ts DESC
            LIMIT 50000
            """,
            (args.days,),
        ).fetchall()
    finally:
        conn.close()

    paints: list[int] = []
    hits = 0
    tiers: dict[str, int] = {}
    slow: list[tuple[int, str, str]] = []

    for (meta,) in rows:
        if meta is None:
            continue
        if isinstance(meta, str):
            try:
                meta = json.loads(meta)
            except json.JSONDecodeError:
                continue
        pm = meta.get("paint_ms")
        if pm is None:
            continue
        try:
            pm = int(pm)
        except (TypeError, ValueError):
            continue
        paints.append(pm)
        if meta.get("cache_hit"):
            hits += 1
        tier = str(meta.get("src_tier") or "unknown")
        tiers[tier] = tiers.get(tier, 0) + 1
        if pm >= 400:
            slow.append((pm, str(meta.get("code") or ""), tier))

    n = len(paints)
    print(f"hero_step samples (last {args.days}d): {n}")
    if n == 0:
        print("No hero_step events yet — swipe covers on the home page to populate.")
        return 0

    paints.sort()
    print(f"  paint_ms  p50={_pct(paints, 0.5)}  p95={_pct(paints, 0.95)}  max={paints[-1]}")
    print(f"  cache_hit rate: {100.0 * hits / n:.1f}%")
    print("  src_tier counts:", ", ".join(f"{k}={v}" for k, v in sorted(tiers.items())))
    if slow:
        print(f"  slow (>=400ms) top 5:")
        for pm, code, tier in sorted(slow, reverse=True)[:5]:
            print(f"    {pm}ms  {code}  ({tier})")
    print()
    print("Interpretation:")
    print("  - High paint_ms + low cache_hit: neighbor prefetch not warm; check mid JPG on disk.")
    print("  - src_tier=api/full dominates: static mid/thumb missing — run export_covers.")
    print("  - p95 > 300ms after mid+prefetch: check main-thread long tasks (DevTools Performance).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
