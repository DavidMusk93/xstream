"""tests/test_ui_star_card.py — Playwright UI regression tests for StarCard.

Locks visual & motion invariants against a live Nuxt frontend (preview on :3100
or production on :3000, overridden via XSTREAM_UI_URL):
  1. Chromatic aura rendering is active (--aura-rgb, glow, gradient) while
     boring palette/mood text labels never appear on the main page.
  2. Hero cover recoil is strictly unidirectional along X and matches the
     gesture direction (swipe left / next -> negative X recoil; swipe right /
     prev -> positive X recoil) with zero vertical squash (scaleY == 1).
  3. Cover & thumbnail images never use object-fit: cover.

Set XSTREAM_UI_SCREENSHOT_DIR=/path to save visual inspection screenshots.
Auto-skips when Playwright Chromium or a local frontend server is unavailable.
"""
from __future__ import annotations

import os
from pathlib import Path
import urllib.request

import pytest

FORBIDDEN_COLOR_LABELS = (
    "Crimson Velvet",
    "Ruby Silk",
    "Blush Rose",
    "Coral Sunset",
    "Champagne Amber",
    "Gilded Honey",
    "Velvet Wine",
    "Obsidian Rose",
    "Orchid Silk",
    "Plum Mirage",
    "Midnight Indigo",
    "Sapphire Dusk",
    "Cerulean Mist",
    "Emerald Noir",
    "Jade Silk",
    "Terracotta Silk",
    "Onsen Steam",
    "Sunlit Shore",
    "Nocturnal Velvet",
    "Glass & Silk",
    "Blush Debut",
    "Crimson Heat",
    "Porcelain Blue",
    "Lace Orchid",
    "Amethyst Tension",
    "Crystal 4K",
)


def _resolve_ui_url() -> str | None:
    explicit = os.environ.get("XSTREAM_UI_URL")
    candidates = [explicit] if explicit else [
        "http://127.0.0.1:3100",
        "http://127.0.0.1:3000",
    ]
    for url in candidates:
        if not url:
            continue
        try:
            with urllib.request.urlopen(f"{url.rstrip('/')}/login", timeout=2) as resp:
                if resp.status < 500:
                    return url.rstrip("/")
        except Exception:
            continue
    return None


def _find_chromium_executable() -> str | None:
    """Locate an installed Chromium binary in ms-playwright cache if default rev mismatches."""
    cache_root = Path.home() / ".cache" / "ms-playwright"
    if not cache_root.exists():
        return None
    patterns = (
        "chromium-*/chrome-linux*/chrome",
        "chromium_headless_shell-*/chrome-headless-shell-linux64/chrome-headless-shell",
        "chromium_headless_shell-*/chrome-linux/headless_shell",
    )
    for pat in patterns:
        matches = sorted(cache_root.glob(pat), reverse=True)
        for m in matches:
            if m.is_file() and os.access(m, os.X_OK):
                return str(m)
    return None


@pytest.fixture(scope="module")
def ui_page():
    playwright_sync = pytest.importorskip("playwright.sync_api")
    base_url = _resolve_ui_url()
    if not base_url:
        pytest.skip("No live xstream frontend on :3100 or :3000 (set XSTREAM_UI_URL)")

    pw = playwright_sync.sync_playwright().start()
    try:
        try:
            browser = pw.chromium.launch(headless=True)
        except Exception:
            exe = _find_chromium_executable()
            if not exe:
                raise
            browser = pw.chromium.launch(headless=True, executable_path=exe)
    except Exception as exc:
        pw.stop()
        pytest.skip(f"Playwright Chromium unavailable: {exc}")

    context = browser.new_context(viewport={"width": 1440, "height": 960})
    context.add_cookies([
        {
            "name": "xstream_auth",
            "value": "ok",
            "url": base_url,
        }
    ])
    page = context.new_page()
    page.goto(f"{base_url}/", wait_until="domcontentloaded", timeout=20000)
    page.wait_for_selector("section.group\\/star .hero-stage", timeout=15000)
    page.wait_for_timeout(400)
    yield page
    browser.close()
    pw.stop()


def _sample_stage_transforms(page, stage_selector: str, duration_ms: int = 520) -> dict:
    """Record DOMMatrix transforms & recoil attributes on rAF for duration_ms."""
    return page.evaluate(
        """([sel, dur]) => new Promise((resolve) => {
          const el = document.querySelector(sel);
          const samples = [];
          const dirs = new Set();
          const start = performance.now();
          function tick(now) {
            const style = getComputedStyle(el);
            const m = new DOMMatrix(style.transform === 'none' ? undefined : style.transform);
            const dir = el.getAttribute('data-recoil-dir');
            if (dir) dirs.add(dir);
            samples.push({
              t: Math.round(now - start),
              a: Number(m.a.toFixed(4)),
              d: Number(m.d.toFixed(4)),
              e: Number(m.e.toFixed(2)),
              f: Number(m.f.toFixed(2)),
              dir: dir || null,
            });
            if (now - start < dur) {
              requestAnimationFrame(tick);
            } else {
              resolve({ samples, dirs: Array.from(dirs) });
            }
          }
          requestAnimationFrame(tick);
        })""",
        [stage_selector, duration_ms],
    )


def test_chromatic_rendering_without_color_name_text(ui_page):
    """Chromatic glow & palette dot render, while color/mood text labels do not."""
    sections = ui_page.locator("section.group\\/star")
    count = sections.count()
    assert count >= 1, "Expected at least one star shelf on home page"

    # Check the first 3 star cards (enough to cover multiple palettes)
    for i in range(min(count, 3)):
        sec = sections.nth(i)
        text = sec.inner_text()
        for label in FORBIDDEN_COLOR_LABELS:
            assert label not in text, f"Boring color/mood label {label!r} leaked into StarCard #{i}"

        # Chromatic CSS custom properties and visual layers must be active
        aura_info = sec.evaluate(
            """(el) => {
              const s = getComputedStyle(el);
              const glow = el.querySelector('.star-aura-glow');
              const btn = el.querySelector('.action-aura');
              return {
                auraRgb: s.getPropertyValue('--aura-rgb').trim(),
                auraDeepRgb: s.getPropertyValue('--aura-deep-rgb').trim(),
                glowBg: glow ? getComputedStyle(glow).backgroundImage : '',
                btnBg: btn ? getComputedStyle(btn).backgroundImage : '',
              };
            }"""
        )
        assert aura_info["auraRgb"], f"Missing --aura-rgb on StarCard #{i}"
        assert aura_info["auraDeepRgb"], f"Missing --aura-deep-rgb on StarCard #{i}"
        assert "radial-gradient" in aura_info["glowBg"], "Star aura glow missing radial-gradient"
        if aura_info["btnBg"]:
            assert "linear-gradient" in aura_info["btnBg"], "Primary action missing aura gradient"

    # Never object-cover on hero or thumbnail images
    bad_imgs = ui_page.evaluate(
        """() => {
          const imgs = Array.from(document.querySelectorAll('section.group\\\\/star img'));
          return imgs
            .filter((img) => getComputedStyle(img).objectFit === 'cover')
            .map((img) => img.getAttribute('src') || img.alt);
        }"""
    )
    assert not bad_imgs, f"Found forbidden object-fit: cover on images: {bad_imgs}"

    shot_dir = os.environ.get("XSTREAM_UI_SCREENSHOT_DIR")
    if shot_dir:
        out = Path(shot_dir)
        out.mkdir(parents=True, exist_ok=True)
        sections.first.scroll_into_view_if_needed()
        ui_page.wait_for_timeout(300)
        ui_page.screenshot(path=str(out / "home_desktop.png"))
        sections.first.screenshot(path=str(out / "star_card_clean.png"))

        # Open palette popover and verify it also stays free of cheesy palette names
        trigger = sections.first.locator("[data-aura-trigger]")
        trigger.click()
        ui_page.wait_for_timeout(250)
        pop_text = sections.first.locator(".popover").inner_text()
        for label in FORBIDDEN_COLOR_LABELS:
            assert label not in pop_text, f"Color label {label!r} leaked into popover"
        sections.first.screenshot(path=str(out / "star_card_popover.png"))
        trigger.click()
        ui_page.wait_for_timeout(200)


def test_directional_horizontal_recoil_no_vertical_squash(ui_page):
    """Swipe left -> left (-X) recoil; swipe right -> right (+X) recoil; scaleY stays 1."""
    # Find a star section with at least 2 titles
    target_id = ui_page.evaluate(
        """() => {
          const secs = Array.from(document.querySelectorAll('section.group\\\\/star'));
          for (const sec of secs) {
            if (sec.querySelectorAll('[data-hero-nav]').length >= 2) {
              return sec.id;
            }
          }
          return null;
        }"""
    )
    if not target_id:
        pytest.skip("No star shelf with >= 2 titles found")

    stage_sel = f"#{target_id} .hero-stage"
    frame_sel = f"#{target_id} .hero-frame"
    stage = ui_page.locator(stage_sel)
    stage.scroll_into_view_if_needed()
    ui_page.wait_for_timeout(200)

    box = ui_page.locator(frame_sel).bounding_box()
    assert box and box["width"] > 200

    cy = box["y"] + box["height"] / 2

    # 1) Swipe LEFT (drag right -> left) to advance to title #2 -> must recoil LEFT (-X)
    ui_page.mouse.move(box["x"] + box["width"] * 0.72, cy)
    ui_page.mouse.down()
    for step in range(1, 7):
        ui_page.mouse.move(box["x"] + box["width"] * (0.72 - 0.06 * step), cy)
        ui_page.wait_for_timeout(12)
    ui_page.mouse.up()

    left_trace = _sample_stage_transforms(ui_page, stage_sel, duration_ms=540)
    assert "left" in left_trace["dirs"], f"Expected 'left' recoil on swipe-left, got {left_trace['dirs']}"
    assert "right" not in left_trace["dirs"], f"Unexpected 'right' recoil on swipe-left: {left_trace['dirs']}"

    min_x = min(s["e"] for s in left_trace["samples"])
    max_scale_y_dev = max(abs(s["d"] - 1.0) for s in left_trace["samples"])
    max_scale_x_dev = max(abs(s["a"] - 1.0) for s in left_trace["samples"])
    assert min_x <= -4.0, f"Expected leftward (-X) recoil <= -4px, got min_x={min_x} ({left_trace['samples'][:12]})"
    assert max_scale_y_dev < 0.001, f"Vertical squash detected (scaleY deviated by {max_scale_y_dev})"
    assert max_scale_x_dev < 0.001, f"Horizontal squash detected (scaleX deviated by {max_scale_x_dev})"

    # Wait for animation to settle
    ui_page.wait_for_timeout(200)

    # 2) Swipe RIGHT (drag left -> right) to return to title #1 -> must recoil RIGHT (+X)
    ui_page.mouse.move(box["x"] + box["width"] * 0.28, cy)
    ui_page.mouse.down()
    for step in range(1, 7):
        ui_page.mouse.move(box["x"] + box["width"] * (0.28 + 0.06 * step), cy)
        ui_page.wait_for_timeout(12)
    ui_page.mouse.up()

    right_trace = _sample_stage_transforms(ui_page, stage_sel, duration_ms=540)
    assert "right" in right_trace["dirs"], f"Expected 'right' recoil on swipe-right, got {right_trace['dirs']}"
    assert "left" not in right_trace["dirs"], f"Unexpected 'left' recoil on swipe-right: {right_trace['dirs']}"

    max_x = max(s["e"] for s in right_trace["samples"])
    max_scale_y_dev_r = max(abs(s["d"] - 1.0) for s in right_trace["samples"])
    max_scale_x_dev_r = max(abs(s["a"] - 1.0) for s in right_trace["samples"])
    assert max_x >= 4.0, f"Expected rightward (+X) recoil >= 4px, got max_x={max_x} ({right_trace['samples'][:12]})"
    assert max_scale_y_dev_r < 0.001, f"Vertical squash detected (scaleY deviated by {max_scale_y_dev_r})"
    assert max_scale_x_dev_r < 0.001, f"Horizontal squash detected (scaleX deviated by {max_scale_x_dev_r})"
