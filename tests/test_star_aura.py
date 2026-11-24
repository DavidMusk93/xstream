"""tests/test_star_aura.py — Chromatic Persona & Desire Aura mapping rules."""
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


def test_star_aura_maps_persona_traits():
    out = _run_ts(r"""
import { computeStarAura, blendRgb, rgbCss } from './utils/starAura.ts';

const veteran = computeStarAura({
  name: 'miru', code: 'SNOS-177',
  titles: [{ code: 'A', release_date_sort: '20181018' }],
});
if (!veteran.careerYears || veteran.careerYears < 6) {
  console.error('veteran:', veteran); process.exit(1);
}

const tall = computeStarAura({
  name: 'Tall Muse', code: 'TEST-001',
  profile: { height_cm: 170, birth_year: 2001 },
  titles: [{ code: 'B', release_date_sort: '20240101' }],
});
if (!['Champagne Amber', 'Gilded Honey'].includes(tall.label)) {
  console.error('tall:', tall); process.exit(1);
}

const curvy = computeStarAura({
  name: 'Curvy Muse', code: 'TEST-002',
  profile: { height_cm: 158, cup: 'H', birth_year: 2002 },
  titles: [{ code: 'C', release_date_sort: '20240501' }],
});
if (!['Crimson Velvet', 'Coral Sunset'].includes(curvy.label)) {
  console.error('curvy:', curvy); process.exit(1);
}

const fresh = computeStarAura({
  name: 'Fresh Debut', code: 'TEST-003',
  profile: { height_cm: 160, birth_year: 2005 },
  titles: [{ code: 'D', release_date_sort: '20260401' }],
});
if (!['Blush Rose', 'Coral Sunset'].includes(fresh.label)) {
  console.error('fresh:', fresh); process.exit(1);
}

// Verify "千人千面" diversity across 20 distinct stars
const labels = new Set<string>();
for (let i = 0; i < 20; i++) {
  const a = computeStarAura({
    name: `Star ${i}`, code: `CODE-${100 + i}`,
    titles: [{ code: `T-${i}`, release_date_sort: `202${i % 6}0501` }],
  });
  labels.add(a.label);
}
if (labels.size < 5) {
  console.error('insufficient chromatic diversity:', [...labels]); process.exit(1);
}

const blended = blendRgb(veteran.primary, { r: 200, g: 120, b: 80 }, 0.35);
if (!rgbCss(blended).includes(',')) process.exit(1);

console.log('ok');
""")
    assert out == "ok"
