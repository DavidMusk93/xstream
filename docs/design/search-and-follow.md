# Search page & follow-a-star (URL parsing, cover proxy)

> TL;DR: Every remote cover goes through `/api/search/cover` (disk cache →
> 307 to `/images/search/<file>`), and `POST /api/stars/add` accepts any
> ijavtorrent actress URL spelling — trailing slash, `http`, `www.`,
> scheme-less, query string — deduping by actress id.

## Why

- ijavtorrent covers live on `images.ijavtorrent.com` (Bunny CDN behind
  Cloudflare) and the CDN **enforces hotlink protection**: a browser-like
  UA without `Referer: https://ijavtorrent.com/` gets 403. That is why every
  hotlinked cover stayed blank in the browser. The library shelves already
  cache covers locally; search was the odd one out.
- The site itself links actress pages with a trailing slash
  (`/actress/julia-326/`), so copy-pasting from the site or from the
  actresses directory produced a 400 ("URL 格式无法解析"). `type="url"` in
  the sheet also rejected scheme-less pastes before the request was even
  sent.
- A name query that ijav's fuzzy full-text search barely answers returned a
  handful of unrelated cards. The matched actress's own listing page is the
  better answer: her works carry covers and actress links.

```
browser  --/api/search-->  backend  --remote cover url-->  images.ijavtorrent.com
                              |
                              +-- first hit: download -> images/search/<sha1>.<ext>
                              +-- later hits: 307 /images/search/<file>  (Caddy static)
```

## Contract

- `GET /api/search?q=` items carry `cover_url = /api/search/cover?u=<quoted>`
  and actresses carry `image` in the same proxied form. Never hotlink the
  CDN from the frontend.
- `GET /api/search/cover?u=` only accepts `images.ijavtorrent.com` /
  `ijavtorrent.com` hosts (no open proxy), sends the ijavtorrent `Referer`
  (hotlink gate), caches under `images/search/` keyed by the URL's sha1 with
  the extension taken from the bytes (the CDN serves WebP under `.jpg`
  URLs), and prunes to the newest 2000 files.
- Name queries: when ijav's full-text search yields < 3 usable cards and the
  actress directory matched, the search falls back to the **best matching
  actress's own page** (`_best_actress_match`: name prefix > substring >
  movie count) and applies the same collection filters.
- `SearchResultStar.code` is the library code when the actress is already
  followed — the UI turns her chip into a `/?star=<code>` deep link, and
  `frontend/pages/index.vue` scrolls to that shelf (query consumed once,
  `replace: true`).
- `scrapers/v2/extractors.py::normalize_actress_url` is the single parser:
  returns `(canonical_url, slug, star_id)`. Dedupe and "already followed"
  checks compare `star_id`, not the URL string (ijav renames slugs).

## Follow UX (no page jumping)

Adding a star used to scroll the library three times: immediately on the
POST response, again on the SSE `star.added` event, and again on
`star.ready`. Now the sheet closes on success and the library scrolls
exactly once — when the new star's titles land (`star.ready`) — so the
shelves no longer shuffle under an open overlay. The scroll itself is
instant, not animated: off-screen shelves reserve an estimated height
(`content-visibility: auto`), so a smooth scroll chases a moving target.

`/?star=<code>` (from a followed actress chip or an actress card in
search) reveals and jumps to that shelf once; the query is consumed with a
`replace` navigation *before* scrolling, because the navigation itself
resets the scroll position.

## Tests

- `tests/test_add_star.py` — URL form matrix, dedupe by actress id,
  non-actress rejection.
- `tests/test_search_router.py` — proxied covers, `/api/search/cover` cache
  + disk redirect + ijav `Referer`, foreign-host rejection, actress
  `code`/`followed`, actress-page fallback for thin name queries.
