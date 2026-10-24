# UI Design — xstream

## Design Philosophy

**Apple-style minimal, light theme, content-first** — aligned with the
[apple-design](https://github.com/emilkowalski/skills) skill (WWDC *Designing
Fluid Interfaces* translated to the web).

- Light background (`#F5F5F7`) with white content surfaces; hierarchy comes
  from whitespace, weight, and proportion — not borders or shadows.
- Every element earns its place: no ambient decoration (no animated blob
  backgrounds, no mouse-follow glows, no gradient buttons, no emoji in UI
  copy).
- One accent color, used sparingly for primary actions and selection states.
- Glassmorphism (`backdrop-filter`) is reserved for floating chrome: the top
  bar, header popovers, toasts, the video modal.
- No floating corner buttons: every tool lives in the top bar.

### Taste (owner feedback, 2026-10)

Rules distilled from the owner's corrections; check new UI against them.

- **The work is the protagonist.** Covers get the space (~60% width on
  desktop); text is a caption to the cover, not a peer column. A cover
  boxed into a card next to empty text reads "not modern".
- **Icons over labels for repeated actions.** Copy / Play / Like are
  icon-only circles; the name lives in a tooltip.
- **Controls live where the action happens and appear on intent.**
  Stepping arrows sit on the cover's edges and show on hover / focus /
  swipe; never a permanent toolbar row for an occasional action.
- **Follow the real workflow.** Users decide after seeing the big cover,
  so copy exists only there — not on every thumbnail.
- **State labels tell the disk truth.** Never echo an engine state word
  (libtorrent `finished`) that contradicts what is actually cached.
- **Motion reference: [archify.si](https://archify.si/zh)** — 0.9s
  rise + fade reveals on `cubic-bezier(0.22,1,0.36,1)`, focus/dim on
  hover, mono numbered eyebrows, big tabular stats split by hairlines;
  hover feedback stays short (~200ms).
- **Logo: sensual through curve and contrast, never explicit imagery.**

---

## Branding

- Logo: a curved Didone-style "x" — one thick swash crossed by a hairline,
  rose → crimson gradient (`#FF8AA0 → #FF375F → #C00036`), a small dot at the
  hairline's tip, on a near-black squircle (`rx 116/512`) with a faint warm
  glow. Sensual through contrast and curve, never through explicit imagery.
- `frontend/public/logo.svg` is the hand-written source; `logo.png`,
  `icon.png` (favicon) and `icon-192x192.png` / `icon-512x512.png` (PWA) are
  rendered from it with headless Chromium (transparent corners). Header
  shows it at 28px next to the `xstream` wordmark; login at 88px.
- Do not reintroduce emoji-as-logo.

---

## Tokens

Defined once in `frontend/tailwind.config.ts`; use the names, not hex.

| Token | Value | Usage |
|---|---|---|
| `void` | `#F5F5F7` | Page background |
| `white` | `#FFFFFF` | Surfaces |
| `fill` | `#F2F2F7` | Image placeholders, sunken areas |
| `foreground` | `#1D1D1F` | Primary text, dark button, active nav pill |
| `foreground-muted` | `#86868B` | Secondary text |
| **`accent`** | `#FF375F` | Copy Magnet / Follow / Search, active thumbnail ring, liked, playhead |
| `success` | `#30D158` | Copied / Following / Finished |
| `warning` | `#FF9F0A` | Verifying, downloading pieces, capacity > 70% |
| `danger` | `#FF453A` | Errors, destructive actions |
| `info` | `#0A84FF` | Downloading state, sync running |
| `shadow-card` | soft 2-layer | Surfaces |
| `shadow-float` | deeper 2-layer | Popovers, sheets, toasts |
| `ease-spring` | `cubic-bezier(0.16, 1, 0.3, 1)` | All enter/hover motion |

Rules:

- **Never** reintroduce `#e50914` (Netflix red), rose/violet gradients, or
  per-section accent colors — one accent only.
- Hairlines are `border-black/[0.05–0.06]`; never hard 1px black dividers.

---

## Component Classes

`frontend/assets/css/main.css` holds the only button/field/surface styles.
Compose them instead of re-spelling utility strings per page.

| Class | What |
|---|---|
| `.chrome` | Fixed top-bar material (blur only from `sm:` — phones skip the per-frame backdrop cost) |
| `.surface` | White card, `rounded-[28px]`, `shadow-card` |
| `.popover` | Floating panel material, `rounded-[22px]`, `shadow-float` |
| `.btn` + `.btn-primary` / `.btn-secondary` / `.btn-dark` / `.btn-success` | Pill buttons, `h-11` (`.btn-sm` = `h-9`) |
| `.btn-icon` | 40px round icon button, hover tint |
| `.action` | 48px round icon-only primary action (Copy / Play / Like); label lives in `data-tip` |
| `.eyebrow` | 12px mono muted row: accent index `01`, count, hairline — section kicker |
| `.field` | Text input, `h-12`, accent focus ring |
| `.chip` | 11px semibold badge (HD, Unavailable, sukebei, In Library) |
| `.spinner` | `currentColor` ring spinner |

Shared components: `ui/AppHeader.vue` (top bar with `leading` / `actions`
slots and a default slot for a second row), `ui/Sheet.vue` (modal: bottom
sheet on phones, centered card from `sm:`), `star/StarCardSkeleton.vue`.

---

## Typography

- System font stack (`-apple-system, SF Pro, Helvetica Neue, system-ui`); no
  webfont. Base body size 17px, line-height 1.5.
- **Size-specific tracking**: headings `-0.022em`; small labels (≤12px)
  keep slightly positive tracking and semibold weight.
- Numbers that change (counts, times, sizes) use `tabular-nums`.

| Role | Mobile | Desktop | Weight |
|------|--------|---------|--------|
| Page large title ("Library") | 40 | 56 | bold |
| Star section header | 28 | 36 | bold |
| Active title code | 34 | 56 (48 at `sm`) | bold, leading 1, `-0.03em` |
| Sheet / section titles | 22 | | bold |
| Panel titles | 17 | | semibold |
| Buttons | 15 (14 small) | | semibold |
| Body / title text | 15 | 17 | regular |
| Meta / dates | 13–14 | | medium |
| Chips, captions | 10–12 | | semibold — never below 10px |

---

## Layout

### Top bar (`AppHeader`)

One glass layer: logo + wordmark (an `Offline` chip appears only when
`/api/health` fails) on the left; icon actions on the right — Search, Play,
Files, Follow (+), X posts, Activity, Downloads, then the dark `Refresh` pill
(spinner + `done/total` while syncing).

The leading slot never shrinks. Below `sm:` the actions are a horizontal
scroll rail (`scrollbar-hide`, `w-max ml-auto` so it right-aligns when it
fits and scrolls from the first icon when it doesn't); a 28px gradient
overlay in the bar color fades whichever edge hides more icons. The fades
are overlays, never a CSS mask — a mask would also clip the `fixed`
popovers rendered inside the rail. From `sm:` up the rail is
`overflow-visible` (popovers anchor under their trigger there). Never let
actions overlap the logo again: add icons to the rail, don't shrink the
logo. On the home page `StarNav` is the second row of the same
layer; the active pill (`bg-foreground text-white`) auto-centers in the rail
as you scroll. The page owns the tracking (a band observer at 30–40% of the
viewport, registered by the same `v-observe` directive that virtualizes
sections); `StarNav` only renders `active` and emits `select`.

At `scrollY < 8` the bar goes flat (`.chrome-flat`: no fill, no hairline) so
the page header breathes; the material returns once content scrolls under.

Activity (`EventPanel`) and Downloads (`CachePanel`) are popovers anchored
under their trigger (`origin-top-right`); full-width sheets under the bar on
phones. Outside pointer-down or Escape closes them (`useDismiss`).

Downloads row status follows disk-verified `progress`, not libtorrent's
`state`: on-demand priorities make libtorrent report `finished` once the
wanted window is in, so `finished`/`seeding` below 99.9% renders as muted
`Partial N%` (`Idle` at 0%). Green `Finished` means the whole video is on
disk.

### Home

Eyebrow `00 Your collection`, large title `Library`, then a stats row
(Stars / Titles / This week — big tabular numbers split by hairlines) over a
soft static accent glow; then one shelf per star. Follow
by URL lives in `AddStarSheet` (with the Recently Added list and a link to
Search), not on the page.

### StarCard (shelf)

Editorial layout, no card box — the cover is the protagonist and the info
reads like a caption. An eyebrow (`01 · N titles ——`, numbered by shelf
order) and the name sit above.

- Stage (`lg:` two columns, `1.65fr / 1fr`; stacked below): hero cover at
  natural aspect ratio (`w-full h-auto`, box reserved from `cover_w/h`), up
  to `760px`, `rounded-[22px]`, soft drop shadow; fades in once decoded.
- Stepping lives on the cover, not in the info column: round glass
  chevrons sit on its left/right edges with a `n / total` pill bottom-right
  (`.hero-nav` / `.hero-count`). Hidden at rest; revealed by hover or
  keyboard focus on desktop, and by a horizontal swipe on touch (the swipe
  itself steps; controls show for 1.6s). The arrow at either end of the
  catalog stays hidden. Vertical drags remain page scroll (`touch-pan-y`).
- Info column (pinned to the bottom on `lg:`): date and HD / Unavailable
  chips, code headline (34 / 48 / 56px, tight tracking), 3–4 line title,
  actions. Swapping titles crossfades the block (`swap`); stepping scrolls
  the gallery to center the new card.
- Actions: three icon-only `.action` circles — **Copy Magnet** (accent
  fill, magnet icon → check + success fill + `Copied` tip), Play (dark fill),
  Like (accent tint when liked). Names come from the `data-tip` tooltip
  (hover on desktop; forced visible after copy via `data-tip-show`).
- Gallery: captioned cards `w-[148/188/212px]`, `rounded-[14px]`, caption =
  code + `YY.MM.DD`. Thumbnails sit in a fixed `aspect-[3/2]` box with
  `object-contain`, so every card shares one height and an abnormal cover
  (portrait, wrong dims) letterboxes instead of stretching the rail —
  `object-cover` stays forbidden. Active = accent dot before the code +
  lifted shadow (no
  ring); inactive covers at `opacity-[0.78]`; dead magnets grayscale.
  Hovering the gallery dims the other cards (focus/dim) and lifts the
  hovered one. The right edge fades out (`.fade-edge-r`). **No copy on
  thumbnails** — users copy only after viewing the hero.
- Unfollow (trash icon) and Inject (X glyph) show on hover on desktop,
  always on touch.
- X posts (`XSocialOverlay`, opened by the header X icon or a shelf's X
  icon — pre-filtered to that star): a floating page (bottom sheet on
  mobile, centered `max-w-[640px]` panel on desktop, `z-[95]`), **not**
  part of the waterfall — posts are transient content and must not occupy
  shelf space. A chip row filters by star; the feed is every bound
  account's newest posts merged and sorted by time, each a card with the
  author line (avatar, name, @handle, relative time, Pinned/Repost chip,
  link-out X glyph), the post's English `en` (original in the tooltip)
  with entities in `info` blue, media as a natural-ratio grid (1 image
  full width, 2–4 in 2 columns), and a likes/views footer. Images come
  from the local cache (`/api/social/x/media` → `/images/x/`, see
  [x-inject.md](x-inject.md)) and stay `opacity-0` until `load` +
  `decode()` succeed (JPEGs paint top-down while downloading, which
  showed half images); a failed image falls back to the original twimg
  URL once. The overlay owns the Inject button (`XInjectSheet`). A bound
  account with no posts only shows `@handle` in the shelf eyebrow.

### Inject from X

`XInjectSheet`, opened from the Inject button inside `XSocialOverlay`
(pre-selected star when the overlay is filtered). Native `<select>`, a
one-line status (`@handle ·
N posts · checked 3h ago`), a monospace textarea, `Not on X` + accent
`Inject`, then a muted "Let an agent do it" box with `Copy brief` and the
accepted formats. Everything is labelled for agents (`aria-label`,
`name`). Protocol: [x-inject.md](x-inject.md).

**Image rule**: preserve original aspect ratio everywhere (covers, actress
photos). Never `object-cover`, never stretch.

### Search

Back + `Search` in the bar; a 56px pill field (inline clear + Search
button). Results: `Actresses` rail (cards with natural-ratio photos and a
Follow button) and `Titles` cards in the StarCard language. Magnet
candidates render as an inset grouped list (resolution, size, seeds, hash,
copy). The card's best-magnet copy is the same icon-only `.action`.

### Files (`/files`, ostore drive)

Same anatomy as Home: the eyebrow is the breadcrumb (`00  Files / 2026 /
clips ——`, segments clickable, current one in `foreground`), the large
title is the current folder (`All Files` at the root), then a stats row
(Folders / Files / Size of this folder). The folder lives in `?path=` so
browser Back goes up a level. Bar actions: New Folder icon + the dark
`Upload` pill (icon-only on phones).

Listing is one `.surface` of rows: a 40px `rounded-[12px]` tile
(`FileTile`: folder = accent tint, video = dark tile with a play glyph,
images = a real thumbnail fitted with `object-contain` on `fill` and
faded in after decode, audio / text / archive = glyph on `fill`, anything
else = its extension as a 10px badge), name 15/17px, one-line truncated
meta `Type · size · 3h ago` 13px. Every row opens on click: folders
navigate, files open the preview. Download / Rename / Delete are
`.btn-icon`s revealed on row hover on pointer devices (Delete hovers to
`danger`); on touch (`hover: none`) they collapse into one `⋯` button
opening a `Sheet` action list (Open / Download / Rename / red Delete), so
the meta line never wraps. Empty state mirrors Home's
(title, one line, `Upload` primary + `New Folder` secondary). Dropping
files anywhere on the page shows a centered `.popover` card ("Drop to
upload into …"); a dragenter/dragleave depth counter keeps it steady.

**Preview** (`FilePreviewModal`) renders every type in the player's
language — `bg-black/90` blurred scrim, stage `rounded-[22px]`
(full-screen on phones), top bar with name, `Type · size`, Download and
Close; StarCard `hero-nav` chevrons on the stage edges plus the `n / total`
pill step through the folder's files (←/→ keys, horizontal swipe; Esc
closes). Media kinds sit on a black stage, document kinds on a white one:

| Kind | Rendering |
|---|---|
| image | fitted `object-contain`, natural ratio, visible only after `decode()` |
| video / audio | native controls (audio: large glyph tile + title + `<audio>`) |
| pdf | browser viewer via `<object>`; fallback card with `Open PDF` |
| markdown | `utils/markdown.ts` (escape-first, http/mailto/relative links only) in a 3xl prose column |
| json | pretty-printed, line-numbered mono |
| csv / tsv | table with sticky header (first 2000 rows) |
| text / code / logs | line-numbered mono, sticky gutter |
| other | sniffed: shown as text when the first 1 MB has no NUL, otherwise a card (extension tile, `Type · size · No preview`, accent `Download`) |

Text kinds fetch only the first 512 KB with a `Range` request and say so
with a sticky footer. Unplayable media falls back to the same card.
Classification lives in one table, `utils/fileKind.ts`.

Rows are patched in place from `files.changed` SSE events — no refetch, no
spinner, no skeleton after the first load (see
[ostore-integration.md](ostore-integration.md)).

### Play (`/play`, any magnet)

Eyebrow `00 Any magnet`, large title `Stream`, one muted line, then the
Search-style 56px pill field (magnet glyph, mono input, inline clear,
accent `Play`). `Recent` is a StarCard-style section header (`01 · N
played ——` + 28/36px title) over a `.surface` row list using the Files
row anatomy (dark play tile, `N MB cached · 2h ago`, hover-revealed
Delete).

### Login

Logo, wordmark, a rotating greeting, passcode field (SVG eye toggle), accent
`Enter`. Wrong passcode shakes the field; typing clears the error.

---

## Motion (apple-design rules)

- **Response on pointer-down**: `.btn` / `.btn-icon` / `.pressable` scale to
  0.97 (icons 0.92) with a 100ms press.
- **Spring easing** (`ease-spring`) for enter/hover; animate only `transform`
  and `opacity`.
- Shared transitions in `main.css`: `pop` (popovers, scale from trigger),
  `fade`, `swap` (in-place content change). `Sheet` slides up on phones and
  scales in on desktop; the player stage scales from 0.96.
- **Scroll reveal** (`v-reveal`, `plugins/reveal.ts`): client-mounted
  blocks rise 14px + fade (+4px blur from `sm:`) over 0.9s on
  `--ease-out` `cubic-bezier(0.22,1,0.36,1)` when they enter the viewport;
  numeric binding = stagger delay. SSR-rendered headers use `.rise` (CSS
  keyframe) instead so hydration never flashes them.
- Hover feedback is short (≈200ms); tooltips wait 250ms.
- Enter and exit share the same path; exits are shorter (~200ms).
- **No slow looping ambient animation.**
- `prefers-reduced-motion`: motion collapses to short opacity cross-fades.
- `prefers-reduced-transparency`: glass goes near-solid, blur off.

---

## Video Player

`VideoModal.vue`: black stage `rounded-[22px]` on a `bg-black/90` blurred
scrim. Top gradient carries the title code and a close button; the bottom
gradient carries the progress bar and bare icon controls (play/pause, mute,
time, fullscreen — 44px hit areas, `hover:bg-white/10`). Loading: spinner,
one status line, a thin white progress bar, one muted detail line. Escape
closes the player in every state.

### Progress bar

`PlayerProgressBar.vue` — also the **download-state map**, fed live by
`torrent.progress` SSE (`piece_segments`, 100 segments ≈ 1% each; see
[sse-push-architecture.md](sse-push-architecture.md)).

Layer stack (bottom → top):

1. Track `bg-white/20`, 4px; thickens to 7px on hover/scrub via `scaleY`.
2. Download-state map per segment:
   - **Cached** (verified on disk): `bg-white/40` — plays instantly.
   - **Downloading**: `bg-amber-400/70` + pulse — arriving now.
   - **Corrupt**: `bg-red-500/60`.
   - **Missing**: transparent (track color shows through).
   - Until the first status arrives, falls back to the browser's
     `video.buffered` ranges (`bg-white/25`).
3. Playhead fill: solid `accent`.
4. Thumb: white dot outside the scaled track (never distorted); scales in on
   hover, grows while scrubbing.

Interactions:

- **Click** seeks.
- **Drag scrub** (Pointer Events + `setPointerCapture`): playhead and bubble
  follow the finger in real time; the seek commits once on release. The
  control bar never auto-hides mid-drag (`scrubbing` event).
- **Hover/drag bubble**: timestamp + state dot and label (`Cached` /
  `Downloading` / `Not cached` / `Corrupt`) for the position under the
  cursor, so the user knows whether a seek target plays instantly *before*
  committing.
- `touch-action: none` on the bar; container swipe/double-tap gestures are
  stopped while interacting with the bar.

The Downloads popover's piece map uses the same semantics on a light track:
cached `foreground/72`, downloading `warning`, corrupt `danger`, missing
transparent.

---

## Interaction Feedback

- Destructive actions keep native `confirm()` (only for irreversible
  deletes).
- Loading: skeletons that match the final layout on first load; `.spinner`
  inside buttons; thin solid progress bars.
- Toasts (`SyncToast`): `.popover` material, top-center under the safe area,
  spring in from above, icon + 14px title + 13px detail, auto-dismiss 4s
  (errors 6s), click to dismiss.

See also [Cache Architecture](cache-architecture.md) for cache panel behavior.
