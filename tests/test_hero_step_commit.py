"""tests/test_hero_step_commit.py — Hero swipe/wheel commit rules (one step per gesture).

Locks the pure commit helpers used by useHeroStepGesture so a long trackpad
flick or a small jitter release cannot map to multiple title steps.
"""

from __future__ import annotations

import subprocess
import sys


def _run_ts(expr: str) -> str:
    proc = subprocess.run(
        ["npx", "--yes", "tsx", "-e", expr],
        cwd="/root/xstream/frontend",
        capture_output=True,
        text=True,
        timeout=30,
        check=True,
    )
    return proc.stdout.strip()


def test_swipe_needs_distance_or_flick():
    out = _run_ts(r"""
import { swipeCommitDirection } from './utils/heroStepCommit.ts';
const w = 400;
const cases = [
  [5, 200, null],
  [-50, 300, 1],
  [80, 400, -1],
  [22, 40, -1],  // fast flick, short travel
  [22, 400, null], // slow drift — jitter
];
for (const [dx, dt, want] of cases) {
  const got = swipeCommitDirection(dx, dt, w);
  const ok = (got === want) || (got == null && want == null);
  if (!ok) { console.error(JSON.stringify({dx, dt, got, want})); process.exit(1); }
}
console.log('ok');
""")
    assert out == "ok"


def test_wheel_commits_once_per_accumulator():
    out = _run_ts(r"""
import { wheelCommitDirection } from './utils/heroStepCommit.ts';
if (wheelCommitDirection(30) !== null) process.exit(1);
if (wheelCommitDirection(100) !== 1) process.exit(1);
if (wheelCommitDirection(-90) !== -1) process.exit(1);
console.log('ok');
""")
    assert out == "ok"
