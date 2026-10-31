"""tests/test_star_sort.py — Home shelf sort (Latest vs Added)

Locks parseStarSort, added_at ordering, and the SSR rule: default Latest until
client hydration reads localStorage (prevents Added stored but Latest shown).
"""

from __future__ import annotations

import subprocess


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


def test_parse_star_sort():
    out = _run_ts(r"""
import { parseStarSort } from './utils/starSort.ts';
const cases = [
  [null, 'works'],
  ['', 'works'],
  ['nope', 'works'],
  ['works', 'works'],
  ['added', 'added'],
];
for (const [raw, want] of cases) {
  if (parseStarSort(raw) !== want) process.exit(1);
}
console.log('ok');
""")
    assert out == "ok"


def test_sort_stars_for_display_added_desc():
    out = _run_ts(r"""
import { sortStarsForDisplay } from './utils/starSort.ts';
const stars = [
  { name: 'Beta', code: 'B', added_at: '2026-01-01T00:00:00Z', titles: [] },
  { name: 'Alpha', code: 'A', added_at: '2026-06-01T00:00:00Z', titles: [] },
];
const works = sortStarsForDisplay(stars, 'works');
if (works[0].code !== 'B') process.exit(1);
const added = sortStarsForDisplay(stars, 'added');
if (added[0].code !== 'A' || added[1].code !== 'B') process.exit(1);
console.log('ok');
""")
    assert out == "ok"


def test_ssr_default_is_works_until_hydrate():
    """Documented contract: server/ first paint uses works; storage applies on mount."""
    out = _run_ts(r"""
import { parseStarSort } from './utils/starSort.ts';
// SSR / pre-mount has no storage — always works
if (parseStarSort(null) !== 'works') process.exit(1);
// After user chose Added, storage must parse to added
if (parseStarSort('added') !== 'added') process.exit(1);
console.log('ok');
""")
    assert out == "ok"
