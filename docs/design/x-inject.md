# X Inject — star X accounts without the X API

Each star can bind one X (x.com) account and show its newest 5 posts in a
floating overlay opened from the header X button. xstream never calls the
X API (paid, rate-limited, unstable) and never scrapes x.com itself.
Content is **injected**: an agent (e.g. Grok browsing with the owner's
account) or the owner pastes what it sees, and the backend normalizes it.

```
 agent / owner browses x.com
        |
        |  HTML | text | JSON          (Inject sheet, or HTTP)
        v
 POST /api/social/x ---> x_inject.parse_payload (off-loop thread)
        |                    |
        |                    v
        |           XProfile[] (handle, name, avatar, <=5 posts)
        v
 db_write(save_x_profile)  merge by post id, keep newest 5
        |
        +--> invalidate_stars_cache()  -> /api/stars carries star.x
        +--> SSE "star.social"         -> clients refetch (ETag)
```

## Inputs (auto-detected, `backend/services/x_inject.py`)

| Form | Shape |
|---|---|
| x.com HTML | outerHTML of a profile/timeline; reads `article[data-testid=tweet]`, `tweetText`, `time[datetime]`, `tweetPhoto`, reply/retweet/like aria-labels, `/analytics` views, `socialContext` (Pinned), `UserName` |
| Text | `@handle` (or profile URL / `handle:` line), then posts split by `---`; each block: status URL, text, optional `time:` / `likes:` / `reposts:` / `replies:` / `views:` lines and pbs.twimg.com image URLs. No separators: each status URL opens a post |
| JSON single | `{"handle", "name", "avatar", "posts": [{"url", "text", "posted_at", "media", "likes", ...}]}` or a bare post list |
| JSON batch | `{"stars": [{"star": "<code\|name\|jp\|ijav handle>", ...single...}]}` |
| Not found | `none` / `not found` / `无`, `{"handle": null}`, `{"found": false}` |
| Translation | per-post `en` (JSON) or an `en:` line (text): English shown on cards instead of the original. `{url, en}` alone is a **patch** that only sets `en` on a stored post |

Normalization rules:

- **Time**: ISO-8601 / epoch / classic API date; missing → derived from the
  status-id snowflake (`(id >> 22) + 1288834974657` ms). Stored naive UTC.
- **Media**: only `https://pbs.twimg.com` (`/media/*` rewritten to
  `name=small` ≈ 680px; video/card thumbs kept); avatar → `_bigger` (73px).
  Anything else is dropped, so injected content cannot make browsers fetch
  arbitrary hosts. Status links are canonicalized to `https://x.com/u/status/id`.
- **English**: cards show `en` when present (original on hover via `title`).
  The agent writes it — concise, cute, flirty, emoji kept; xstream has no
  LLM key and never translates server-side. A re-inject without `en` keeps
  the stored translation while the original text is unchanged.
- Text clamped to 1200 chars (`en` 600); posts deduped by id (text hash when no URL);
  newest 5 kept (ties broken by snowflake id).

## Storage (see `database.md`)

- `stars.x_handle / x_name / x_avatar / x_checked_at`. `x_checked_at` set
  with `x_handle NULL` = "checked, no account" (agents skip it).
- `social_posts` rows with `platform='x'`, `post_id`, `media JSONB`,
  `meta JSONB {stats, pinned, author, en}`.
- `save_x_profile` semantics: posts **merge** with stored ones by id (an
  inject of 2 new posts keeps the other 3); a **different handle** replaces
  the account and drops its posts; not-found clears both; name/avatar keep
  the stored value when the inject omits them.

## API

- `POST /api/social/x` `{"star": "<code|name>|null", "content": <str|object>}`
  → `{"updated", "results": [{star, name, ok, handle, posts, received, error}]}`.
  `star` targets single-star payloads; batch JSON names its own stars.
  422 = unparseable, 404 = no star matched, 413 = > 2MB.
- `GET /api/social/x/pending?stale_hours=72` → stars never checked or stale,
  plus an `inject` block describing the format (self-documenting for agents).

## UI

- The header X icon opens `XSocialOverlay`: a floating page (bottom sheet
  on mobile, centered panel on desktop) merging every bound account's
  newest posts into one time-sorted feed, with star filter chips. Posts
  are transient content and never occupy the waterfall. The per-star X
  icon (next to unfollow) opens the same overlay pre-filtered to that
  star; the overlay's Inject button opens `XInjectSheet` (Auto = batch),
  native star `<select>`, status line, monospace textarea
  (`name="content"`, ⌘/Ctrl+Enter submits), `Not on X` and `Inject`.
  "Copy brief" copies a ready prompt for an agent listing the selected or
  pending stars (stale, or with posts lacking `en`) and the JSON reply
  shape, including the `en` style rule.
- `XSocialOverlay` cards: author line (avatar, name, @handle, relative
  time, Pinned/Repost chip, link-out), `en` text (original on hover via
  `title`), media as a natural-ratio grid, likes/views footer; text
  renders via interpolation, never `v-html` (layout detail:
  `ui-design.md`).
- Cost: posts ride the existing ETag-cached `/api/stars` payload (≈1–2KB
  per bound star); no timers or polling; images are lazy, `decode()`
  gated, and served from the local media cache below.

## Media cache (`backend/services/x_media.py`)

Injected posts reference `pbs.twimg.com` images; hotlinking them loaded
poorly for users, so media is cached on this machine and served like a
CDN (mirrors the `/api/cover` pattern):

```
 inject POST /api/social/x
   -> x_media.warm(avatar + post media)   (background, best-effort)
        -> images/x/{blake2b(url)[:24]}.{ext}   (atomic, image/*, <=12MB)
 /api/stars payload (stars.py)
   -> avatar/media rewritten to
      /api/social/x/media/{filename}?u=<original twimg URL>
 GET /api/social/x/media/{filename}
   -> disk hit:  307 /images/x/{filename}  (Caddy static, immutable 30d)
   -> disk miss: fetch u, cache, serve bytes (same cache headers)
```

- Only `https://pbs.twimg.com` is ever fetched — the endpoint can never
  act as an open proxy. The original URL travels in `u`, so no hash→URL
  mapping table exists and the client can fall back to the remote URL on
  error.
- `/images/x/` is served by Caddy's existing `/images/*` static block;
  `/api/social/x/media/*` is excluded from Caddy compression, and the PWA
  caches it CacheFirst like covers.
