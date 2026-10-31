# Hero cover step — paint metrics

When the user steps the shelf hero (swipe, wheel, arrows), the frontend
emits `hero_step` via `/api/track`:

| meta field | Meaning |
|---|---|
| `paint_ms` | Time from title change until the cover is decoded and shown |
| `cache_hit` | Neighbor prefetch had already decoded this code |
| `src_tier` | `mid` / `thumb` / `full` / `api` — which URL tier was used |

## Query (production)

```bash
set -a; . /etc/xstream.env; set +a
uv run python scripts/analyze_hero_step_metrics.py --days 7
```

## Root causes we optimize against

1. **Full-size `src`** — decoding a 1600px JPEG for a 760px box stalls the
   main thread. Hero uses `cover_mid_url` (800w) when present.
2. **Cold image** — every step reset `opacity-0` until load. Module-level
   prefetch + decode cache keeps neighbors warm; cache hits skip the fade.
3. **Per-step img swap** — `<Transition>` destroyed/mounted hero `<img>` nodes.
   Fixed: horizontal `.hero-track` + fixed 3/2 stage; slide transition.
4. **Thumbnail rail scroll → Vue window** — every scroll pixel updated refs
   and remounted `v-for` thumbs. Fixed: rAF + expand-only window;
   `contain: strict` on `.thumb-rail`; stepping uses instant scroll.
5. **Cold neighbor on drag/wheel** — prefetch waits until commit. Fixed:
   `onHorizontalDrag` / `onWheelAccumulate` widen the hero slide window
   and decode the peeked title before release.

## Targets (after mid + prefetch)

| Metric | Good | Investigate |
|---|---|---|
| `paint_ms` p50 | < 80ms (cache_hit) | > 200ms |
| `paint_ms` p95 | < 250ms | > 400ms |
| `cache_hit` rate | > 60% on sequential browse | < 40% |
| `src_tier=mid` share | > 90% of library | `api`/`full` dominant |

If `src_tier=api` dominates, run `scripts/export_covers.py` so `/api/stars`
emits static mid/thumb URLs.
