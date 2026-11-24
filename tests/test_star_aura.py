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
import { STAR_PALETTES, computeStarAura, computeTitleMood, blendRgb, rgbCss } from './utils/starAura.ts';

if (STAR_PALETTES.length !== 16) {
  console.error('expected 16 palettes, got', STAR_PALETTES.length); process.exit(1);
}

const explicit = computeStarAura({
  name: 'Custom Muse', code: 'TEST-000',
  profile: { style: 'emerald-noir' },
  titles: [{ code: 'Z', release_date_sort: '20250101' }],
});
if (explicit.id !== 'emerald-noir' || explicit.label !== 'Emerald Noir') {
  console.error('explicit override:', explicit); process.exit(1);
}

const tall = computeStarAura({
  name: 'Tall Muse', code: 'TEST-001',
  profile: { height_cm: 170, birth_year: 2001 },
  titles: [{ code: 'B', release_date_sort: '20240101' }],
});
if (!['Champagne Amber', 'Gilded Honey', 'Sapphire Dusk', 'Terracotta Silk'].includes(tall.label)) {
  console.error('tall:', tall); process.exit(1);
}

// Verify per-work mood differentiation
const m1 = computeTitleMood({ code: 'A-1', title: '二人きりの温泉旅館で混浴' });
const m2 = computeTitleMood({ code: 'A-2', title: '残業オフィスで黒スト秘書と' });
const m3 = computeTitleMood({ code: 'A-3', title: '真夏のビーチでビキニ' });
if (m1?.label !== 'Onsen Steam' || m2?.label !== 'Glass & Silk' || m3?.label !== 'Sunlit Shore') {
  console.error('title moods:', { m1, m2, m3 }); process.exit(1);
}

// Verify 16-palette diversity across 32 distinct stars
const ids = new Set<string>();
for (let i = 0; i < 32; i++) {
  const a = computeStarAura({
    name: `Star ${i}`, code: `CODE-${100 + i}`,
    titles: [{ code: `T-${i}`, release_date_sort: `202${i % 6}0501` }],
  });
  ids.add(a.id);
}
if (ids.size < 8) {
  console.error('insufficient chromatic diversity:', [...ids]); process.exit(1);
}

const blended = blendRgb(explicit.primary, m1.rgb, 0.34);
if (!rgbCss(blended).includes(',')) process.exit(1);

console.log('ok');
""")
    assert out == "ok"
