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

---

## Branding

- Logo: neon star with a play glyph on a dark rounded square
  (`frontend/public/logo.png`; `logo.svg` is the source). Header shows it at
  28px next to the `xstream` wordmark; login shows it at 88px.
- `icon.png` (favicon) and `icon-192x192.png` / `icon-512x512.png` (PWA).
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
| Page large title ("Library") | 34 | 44 | bold |
| Star section header | 26 | 32 | bold |
| Active title code | 30 | 40 | bold, leading 1.05 |
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
`/api/health` fails) on the left; icon actions on the right — Search, Follow
(+), Activity, Downloads, then the dark `Refresh` pill (spinner + `done/total`
while syncing). On the home page `StarNav` is the second row of the same
layer; the active pill (`bg-foreground text-white`) auto-centers in the rail
as you scroll.

Activity (`EventPanel`) and Downloads (`CachePanel`) are popovers anchored
under their trigger (`origin-top-right`); full-width sheets under the bar on
phones. Outside pointer-down or Escape closes them (`useDismiss`).

### Home

Large title `Library` + `N stars · M titles`, then one shelf per star. Follow
by URL lives in `AddStarSheet` (with the Recently Added list and a link to
Search), not on the page.

### StarCard (shelf)

Name + `N titles · No. X` sit on the page; the shelf is one `.surface`
holding the hero and the thumbnail rail (hairline between them).

- Hero cover: natural aspect ratio (`w-full h-auto`, box reserved from
  `cover_w/h`), `sm:300 / md:360 / lg:440px`, `rounded-[18px]`; fades in once
  decoded.
- Info: meta line (`#N · date`, HD / Unavailable chips), code headline,
  3-line title. Swapping titles crossfades the info block (`swap`).
- Actions: **Copy Magnet** (accent, primary — the real workflow), Play
  (secondary), Like (round icon; accent tint when liked). On phones the two
  pill buttons share the row equally.
- Rail: `w-[112/144/168px]`, `rounded-xl`; active = `ring-2 ring-accent
  ring-offset-2`, inactive `opacity-[0.72]`; dead magnets grayscale. Hover
  reveals the one-click copy button.
- Unfollow (trash icon) shows on hover on desktop, always on touch.

**Image rule**: preserve original aspect ratio everywhere (covers, actress
photos). Never `object-cover`, never stretch.

### Search

Back + `Search` in the bar; a 56px pill field (inline clear + Search
button). Results: `Actresses` rail (cards with natural-ratio photos and a
Follow button) and `Titles` cards in the StarCard language. Magnet
candidates render as an inset grouped list (resolution, size, seeds, hash,
copy).

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
