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
  [22, 40, -1],   // fast flick, short travel
  [22, 400, null], // slow drift — jitter
  [-360, 80, 1],  // fast long swipe must still commit strictly 1 slide
  [360, 80, -1],  // fast long reverse swipe must still commit strictly -1 slide
];
for (const [dx, dt, want] of cases) {
  const got = swipeCommitDirection(dx, dt, w);
  const ok = (got === want) || (got == null && want == null);
  if (!ok) { console.error(JSON.stringify({dx, dt, got, want})); process.exit(1); }
}
console.log('ok');
""")
    assert out == "ok"


def test_wheel_inertia_lockout_and_rubber_band():
    out = _run_ts(r"""
import { isNewWheelGesture, rubberBandDrag } from './utils/heroStepCommit.ts';
// Decaying macOS inertia tail in same direction must NOT unlock
if (isNewWheelGesture(20, 30, true, 120)) process.exit(1);
if (isNewWheelGesture(10, 15, true, 400)) process.exit(1);
// Deliberate re-acceleration spike after cooldown DOES unlock
if (!isNewWheelGesture(45, 8, true, 350)) process.exit(1);
// Direction reversal after 160ms DOES unlock
if (!isNewWheelGesture(12, 20, false, 180)) process.exit(1);
// Tiny reverse jitter too soon does NOT unlock
if (isNewWheelGesture(4, 20, false, 180)) process.exit(1);
// Rubber-band damps at bounds, 1:1 in middle
if (rubberBandDrag(100, false, false) !== 100) process.exit(1);
const damped = rubberBandDrag(100, true, false);
if (!(damped > 0 && damped < 25)) process.exit(1);
console.log('ok');
""")
    assert out == "ok"


def test_gesture_target_rejects_non_element():
    out = _run_ts(r"""
import { isHeroCoverGestureTarget } from './utils/heroStepCommit.ts';
if (isHeroCoverGestureTarget(null)) process.exit(1);
if (isHeroCoverGestureTarget({})) process.exit(1);
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
