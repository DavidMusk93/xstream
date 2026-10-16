"""backend/services/x_inject.py — Parse injected X (Twitter) content

xstream never calls the X API. An agent (or the owner) browses x.com and
injects what it sees through POST /api/social/x; this module turns that
payload into normalized profiles. Accepted inputs, auto-detected:

  1. JSON — one star ``{"handle", "posts": [...]}``, a bare post list, or a
     batch ``{"stars": [{"star": "<code|name>", ...}]}``. ``"handle": null``
     (or ``"found": false``) marks the star as checked with no account.
  2. x.com HTML — outerHTML of the profile page / timeline; ``article``
     tweets are read via X's ``data-testid`` hooks.
  3. Plain text — post blocks separated by ``---`` lines; a status URL, an
     ISO time and pbs.twimg.com image URLs are picked out of each block,
     ``key: value`` lines (likes / reposts / replies / views / time) too.
     A lone ``none`` / ``not found`` / ``无`` means no account.

Only https pbs.twimg.com media is kept (rewritten to the ``small`` variant)
and only x.com status links, so injected content can never make the
browser fetch arbitrary hosts.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections import Counter
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
from urllib.parse import parse_qs, urlencode, urlsplit

MAX_POSTS = 5
MAX_TEXT = 1200
MAX_MEDIA = 4
MAX_NAME = 80

_X_EPOCH_MS = 1288834974657
_HANDLE_RE = re.compile(r"^[A-Za-z0-9_]{1,15}$")
_RESERVED = {
    "home", "i", "search", "explore", "notifications", "messages", "settings",
    "intent", "share", "hashtag", "compose", "login", "signup", "tos", "privacy",
}
_STATUS_RE = re.compile(
    r"(?:https?://(?:www\.|mobile\.)?(?:x|twitter)\.com)?/([A-Za-z0-9_]{1,15})/status(?:es)?/(\d{5,25})"
)
_PROFILE_RE = re.compile(r"https?://(?:www\.|mobile\.)?(?:x|twitter)\.com/([A-Za-z0-9_]{1,15})(?![\w/]*status)")
_AT_LINE_RE = re.compile(r"^@([A-Za-z0-9_]{1,15})$")
_MEDIA_RE = re.compile(r"https://pbs\.twimg\.com/[^\s\"'<>)]+")
_NONE_RE = re.compile(r"^(none|null|n/?a|not\s*found|no\s*account|无|没有|未找到|找不到)\.?$", re.I)
_SEPARATOR_RE = re.compile(r"^\s*(?:-{3,}|={3,}|\*{3,})\s*$")
_KV_RE = re.compile(r"^(\w+)\s*[:=]\s*(.+)$")
_COUNT_RE = re.compile(r"^\s*([\d.,]+)\s*([KkMm万千億亿]?)")

_STAT_ALIASES = {
    "replies": "replies", "reply": "replies", "reply_count": "replies", "comments": "replies",
    "reposts": "reposts", "repost": "reposts", "retweets": "reposts", "retweet": "reposts",
    "retweet_count": "reposts", "repost_count": "reposts",
    "likes": "likes", "like": "likes", "favorites": "likes", "favorite_count": "likes",
    "like_count": "likes", "hearts": "likes",
    "views": "views", "view": "views", "view_count": "views", "impressions": "views",
}
_TIME_KEYS = ("posted_at", "time", "date", "created_at", "timestamp", "datetime")
_TEXT_KEYS = ("text", "content", "full_text", "body")
_URL_KEYS = ("url", "link", "permalink", "post_url")
_MEDIA_KEYS = ("media", "images", "photos", "image")
_HANDLE_KEYS = ("handle", "username", "screen_name", "x", "account", "user")
_NAME_KEYS = ("name", "display_name", "x_name")
_AVATAR_KEYS = ("avatar", "avatar_url", "profile_image", "profile_image_url", "x_avatar")


class InjectError(ValueError):
    """Payload could not be understood."""


@dataclass
class XPost:
    id: str
    text: str
    url: str | None = None
    posted_at: datetime | None = None
    media: list[str] = field(default_factory=list)
    stats: dict[str, int] = field(default_factory=dict)
    pinned: bool = False
    author: str | None = None


@dataclass
class XProfile:
    star: str | None = None
    handle: str | None = None
    name: str | None = None
    avatar: str | None = None
    posts: list[XPost] = field(default_factory=list)
    not_found: bool = False


# ── Normalizers ─────────────────────────────────────────────────────

def clean_handle(raw: Any) -> str | None:
    if not isinstance(raw, str):
        return None
    s = raw.strip()
    m = _PROFILE_RE.match(s) or _STATUS_RE.match(s)
    if m:
        s = m.group(1)
    s = s.lstrip("@")
    if not _HANDLE_RE.match(s) or s.lower() in _RESERVED:
        return None
    return s


def snowflake_time(post_id: str) -> datetime | None:
    try:
        ms = (int(post_id) >> 22) + _X_EPOCH_MS
    except ValueError:
        return None
    # Pre-2010-11 ids are sequential, not snowflakes.
    if ms <= _X_EPOCH_MS + 1000:
        return None
    return datetime.fromtimestamp(ms / 1000, UTC).replace(tzinfo=None)


def post_order(post_id: str | None) -> int:
    """Tie-break for posts in the same millisecond: snowflake ids grow."""
    return int(post_id) if post_id and post_id.isdigit() else 0


def parse_time(raw: Any) -> datetime | None:
    if raw is None or raw == "":
        return None
    if isinstance(raw, (int, float)):
        secs = raw / 1000 if raw > 1e11 else raw
        try:
            return datetime.fromtimestamp(secs, UTC).replace(tzinfo=None)
        except (OverflowError, OSError, ValueError):
            return None
    if not isinstance(raw, str):
        return None
    s = raw.strip()
    if s.isdigit():
        return parse_time(int(s))
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        try:
            # Classic API form: "Wed Oct 10 20:19:24 +0000 2018"
            dt = datetime.strptime(s, "%a %b %d %H:%M:%S %z %Y")
        except ValueError:
            return None
    if dt.tzinfo is not None:
        dt = dt.astimezone(UTC).replace(tzinfo=None)
    return dt


def parse_count(raw: Any) -> int | None:
    if isinstance(raw, bool):
        return None
    if isinstance(raw, (int, float)):
        return max(0, int(raw))
    if not isinstance(raw, str):
        return None
    m = _COUNT_RE.match(raw)
    if not m:
        return None
    num, unit = m.groups()
    unit = unit.lower()
    # "1,234" is a thousands separator; "1,2K" (EU decimal) is rare enough to ignore.
    num = num.replace(",", "")
    try:
        value = float(num)
    except ValueError:
        return None
    value *= {"k": 1e3, "千": 1e3, "m": 1e6, "万": 1e4, "億": 1e8, "亿": 1e8}.get(unit, 1)
    return int(value)


def clean_media(raw: Any) -> str | None:
    if not isinstance(raw, str):
        return None
    url = raw.strip()
    parts = urlsplit(url)
    if parts.scheme != "https" or parts.hostname != "pbs.twimg.com":
        return None
    path = parts.path
    if path.startswith("/profile_images/"):
        return None
    if path.startswith("/media/"):
        # Rewrite to the ~680px "small" variant: plenty for a 320px card at 2x
        # and a fraction of the "large"/"orig" bytes.
        qs = parse_qs(parts.query)
        fmt = (qs.get("format") or [""])[0]
        m = re.match(r"^(/media/[\w-]+)(?:\.(\w+))?", path)
        if not m:
            return None
        fmt = fmt or m.group(2) or "jpg"
        return f"https://pbs.twimg.com{m.group(1)}?{urlencode({'format': fmt, 'name': 'small'})}"
    if re.match(r"^/(ext_tw_video_thumb|amplify_video_thumb|tweet_video_thumb|card_img)/", path):
        return f"https://pbs.twimg.com{path}" + (f"?{parts.query}" if parts.query else "")
    return None


def clean_avatar(raw: Any) -> str | None:
    if not isinstance(raw, str):
        return None
    parts = urlsplit(raw.strip())
    if parts.scheme != "https" or parts.hostname != "pbs.twimg.com":
        return None
    if not parts.path.startswith("/profile_images/"):
        return None
    # 73px "bigger" variant covers a 32px avatar at 2x.
    path = re.sub(r"_(normal|bigger|mini|200x200|400x400)(\.\w+)$", r"_bigger\2", parts.path)
    return f"https://pbs.twimg.com{path}"


def clean_text(raw: Any) -> str:
    if not isinstance(raw, str):
        return ""
    s = raw.replace("\r\n", "\n").replace("\u00a0", " ")
    s = re.sub(r"[ \t]+\n", "\n", s)
    s = re.sub(r"\n{3,}", "\n\n", s).strip()
    if len(s) > MAX_TEXT:
        s = s[: MAX_TEXT - 1].rstrip() + "…"
    return s


def _status_parts(url: Any) -> tuple[str, str] | None:
    if not isinstance(url, str):
        return None
    m = _STATUS_RE.search(url)
    return (m.group(1), m.group(2)) if m else None


def _make_post(
    *,
    text: str = "",
    url: str | None = None,
    posted_at: datetime | None = None,
    media: list[str] | None = None,
    stats: dict[str, int] | None = None,
    pinned: bool = False,
    author: str | None = None,
    post_id: str | None = None,
) -> XPost | None:
    text = clean_text(text)
    media = [m for m in dict.fromkeys(media or []) if m][:MAX_MEDIA]
    status = _status_parts(url)
    canonical_url = None
    if status:
        author = author or status[0]
        post_id = status[1]
        canonical_url = f"https://x.com/{status[0]}/status/{status[1]}"
    if not text and not media:
        return None
    if post_id and not post_id.isdigit():
        post_id = None
    if posted_at is None and post_id:
        posted_at = snowflake_time(post_id)
    if not post_id:
        post_id = "h" + hashlib.blake2b(text.encode("utf-8"), digest_size=8).hexdigest()
    return XPost(
        id=post_id,
        text=text,
        url=canonical_url,
        posted_at=posted_at,
        media=media,
        stats={k: v for k, v in (stats or {}).items() if v is not None},
        pinned=pinned,
        author=clean_handle(author) if author else None,
    )


def _finalize(profile: XProfile) -> XProfile:
    if profile.not_found:
        profile.handle = profile.name = profile.avatar = None
        profile.posts = []
        return profile
    if not profile.handle:
        # Infer from the posts' own status URLs — the most common author.
        authors = Counter(p.author for p in profile.posts if p.author)
        if authors:
            profile.handle = authors.most_common(1)[0][0]
    seen: set[str] = set()
    unique: list[XPost] = []
    for p in profile.posts:
        if p.id in seen:
            continue
        seen.add(p.id)
        unique.append(p)
    unique.sort(key=lambda p: (p.posted_at or datetime.min, post_order(p.id)), reverse=True)
    profile.posts = unique[:MAX_POSTS]
    if profile.name:
        profile.name = clean_text(profile.name)[:MAX_NAME] or None
    if not profile.handle and not profile.posts:
        raise InjectError("no X handle or posts recognized")
    return profile


# ── JSON ────────────────────────────────────────────────────────────

def _first(d: dict[str, Any], keys: tuple[str, ...]) -> Any:
    for k in keys:
        if k in d and d[k] not in (None, ""):
            return d[k]
    return None


def _json_post(item: Any) -> XPost | None:
    if isinstance(item, str):
        return _text_block(item.splitlines())
    if not isinstance(item, dict):
        return None
    raw_media = _first(item, _MEDIA_KEYS) or []
    if isinstance(raw_media, (str, dict)):
        raw_media = [raw_media]
    media = [clean_media(m.get("url") if isinstance(m, dict) else m) for m in raw_media]
    stats_src = item.get("stats") if isinstance(item.get("stats"), dict) else item
    stats: dict[str, int] = {}
    for k, v in stats_src.items():
        key = _STAT_ALIASES.get(k.lower()) if isinstance(k, str) else None
        if key and (n := parse_count(v)) is not None:
            stats[key] = n
    url = _first(item, _URL_KEYS)
    post_id = item.get("id") or item.get("id_str")
    return _make_post(
        text=_first(item, _TEXT_KEYS) or "",
        url=url,
        posted_at=parse_time(_first(item, _TIME_KEYS)),
        media=[m for m in media if m],
        stats=stats,
        pinned=bool(item.get("pinned")),
        author=clean_handle(item.get("author")),
        post_id=str(post_id) if post_id is not None else None,
    )


def _json_profile(obj: dict[str, Any], default_star: str | None) -> XProfile:
    star = obj.get("star") or obj.get("code") or default_star
    profile = XProfile(star=str(star) if star else None)
    handle_present = any(k in obj for k in _HANDLE_KEYS)
    raw_handle = _first(obj, _HANDLE_KEYS)
    if obj.get("found") is False or obj.get("not_found") is True or (handle_present and raw_handle is None):
        profile.not_found = True
        return _finalize(profile)
    if raw_handle is not None:
        profile.handle = clean_handle(raw_handle)
        if not profile.handle:
            raise InjectError(f"invalid X handle: {str(raw_handle)[:40]!r}")
    profile.name = _first(obj, _NAME_KEYS) if isinstance(_first(obj, _NAME_KEYS), str) else None
    profile.avatar = clean_avatar(_first(obj, _AVATAR_KEYS))
    posts = obj.get("posts") or obj.get("tweets") or []
    if not isinstance(posts, list):
        raise InjectError("'posts' must be a list")
    profile.posts = [p for p in (_json_post(i) for i in posts) if p]
    return _finalize(profile)


def _parse_json(data: Any, default_star: str | None) -> list[XProfile]:
    if isinstance(data, dict) and isinstance(data.get("stars"), list):
        return [_json_profile(item, None) for item in data["stars"] if isinstance(item, dict)]
    if isinstance(data, dict):
        return [_json_profile(data, default_star)]
    if isinstance(data, list):
        if data and all(isinstance(i, dict) and "star" in i for i in data):
            return [_json_profile(item, None) for item in data]
        return [_json_profile({"posts": data}, default_star)]
    raise InjectError("JSON must be an object or a list")


# ── HTML (x.com DOM) ────────────────────────────────────────────────

def _node_text(node) -> str:
    # X renders emoji as <img alt="😀">; keep them as text.
    for img in node.css("img"):
        img.replace_with(img.attributes.get("alt") or "")
    return node.text(separator="", strip=False)


def _aria_count(node) -> int | None:
    if node is None:
        return None
    label = node.attributes.get("aria-label") or node.text(strip=True)
    return parse_count(label or "")


def _parse_html(html: str, default_star: str | None) -> list[XProfile]:
    from selectolax.parser import HTMLParser

    tree = HTMLParser(html)
    profile = XProfile(star=default_star)

    user_name = tree.css_first('[data-testid="UserName"]')
    if user_name is not None:
        m = re.search(r"@([A-Za-z0-9_]{1,15})", user_name.text())
        if m:
            profile.handle = clean_handle(m.group(1))
        first_span = user_name.css_first("span")
        if first_span is not None:
            profile.name = _node_text(first_span).strip() or None
    if not profile.handle:
        canonical = tree.css_first('link[rel="canonical"]')
        if canonical is not None:
            profile.handle = clean_handle(canonical.attributes.get("href") or "")

    articles = tree.css('article[data-testid="tweet"]') or tree.css("article")
    for art in articles:
        time_el = art.css_first("time[datetime]")
        url = None
        if time_el is not None and time_el.parent is not None and time_el.parent.tag == "a":
            url = time_el.parent.attributes.get("href")
        if not url:
            for a in art.css('a[href*="/status/"]'):
                href = a.attributes.get("href") or ""
                if _STATUS_RE.search(href) and "/photo/" not in href and "/analytics" not in href:
                    url = href
                    break
        text_el = art.css_first('[data-testid="tweetText"]')
        media: list[str] = []
        for img in art.css('[data-testid="tweetPhoto"] img, img[src*="/media/"]'):
            media.append(clean_media(img.attributes.get("src")) or "")
        for video in art.css("video[poster]"):
            media.append(clean_media(video.attributes.get("poster")) or "")
        social = art.css_first('[data-testid="socialContext"]')
        social_text = social.text(strip=True).lower() if social is not None else ""
        stats = {
            "replies": _aria_count(art.css_first('[data-testid="reply"]')),
            "reposts": _aria_count(art.css_first('[data-testid="retweet"], [data-testid="unretweet"]')),
            "likes": _aria_count(art.css_first('[data-testid="like"], [data-testid="unlike"]')),
            "views": _aria_count(art.css_first('a[href$="/analytics"]')),
        }
        post = _make_post(
            text=_node_text(text_el) if text_el is not None else "",
            url=url,
            posted_at=parse_time(time_el.attributes.get("datetime")) if time_el is not None else None,
            media=[m for m in media if m],
            stats=stats,
            pinned="pinned" in social_text or "置顶" in social_text or "固定" in social_text,
        )
        if post:
            profile.posts.append(post)
        if not profile.avatar and post and post.author and profile.handle and post.author.lower() == profile.handle.lower():
            avatar = art.css_first('img[src*="profile_images"]')
            if avatar is not None:
                profile.avatar = clean_avatar(avatar.attributes.get("src"))

    if not profile.avatar and profile.handle:
        for img in tree.css('img[src*="profile_images"]'):
            profile.avatar = clean_avatar(img.attributes.get("src"))
            if profile.avatar:
                break
    return [_finalize(profile)]


# ── Plain text ──────────────────────────────────────────────────────

def _text_block(lines: list[str]) -> XPost | None:
    text_lines: list[str] = []
    url = None
    posted_at = None
    media: list[str] = []
    stats: dict[str, int] = {}
    pinned = False
    for line in lines:
        s = line.strip()
        status = _STATUS_RE.search(s)
        if status and s.strip("<>()[] ") == status.group(0).strip():
            url = url or status.group(0)
            continue
        media_urls = _MEDIA_RE.findall(s)
        if media_urls and not _MEDIA_RE.sub("", s).strip():
            media.extend(m for m in (clean_media(u) for u in media_urls) if m)
            continue
        kv = _KV_RE.match(s)
        if kv:
            key, value = kv.group(1).lower(), kv.group(2).strip()
            if key in _STAT_ALIASES and (n := parse_count(value)) is not None:
                stats[_STAT_ALIASES[key]] = n
                continue
            if key in _TIME_KEYS and (t := parse_time(value)):
                posted_at = t
                continue
            if key in _URL_KEYS and _status_parts(value):
                url = value
                continue
            if key == "pinned":
                pinned = value.lower() in ("1", "true", "yes", "y")
                continue
            if key in _TEXT_KEYS:
                text_lines.append(value)
                continue
        if s and posted_at is None and (t := parse_time(s)) and not s.isdigit():
            posted_at = t
            continue
        text_lines.append(line.rstrip())
    return _make_post(
        text="\n".join(text_lines), url=url, posted_at=posted_at,
        media=media, stats=stats, pinned=pinned,
    )


def _parse_text(text: str, default_star: str | None) -> list[XProfile]:
    profile = XProfile(star=default_star)
    if _NONE_RE.match(text.strip()):
        profile.not_found = True
        return [_finalize(profile)]

    body: list[str] = []
    for line in text.splitlines():
        s = line.strip()
        kv = _KV_RE.match(s)
        if kv and kv.group(1).lower() in _HANDLE_KEYS + _NAME_KEYS + _AVATAR_KEYS + ("star",):
            key, value = kv.group(1).lower(), kv.group(2).strip()
            if key == "star":
                profile.star = value
            elif key in _HANDLE_KEYS:
                if _NONE_RE.match(value):
                    profile.not_found = True
                else:
                    profile.handle = clean_handle(value) or profile.handle
            elif key in _NAME_KEYS:
                profile.name = value
            else:
                profile.avatar = clean_avatar(value)
            continue
        at = _AT_LINE_RE.match(s)
        prof = _PROFILE_RE.fullmatch(s)
        if (at or prof) and not profile.handle:
            profile.handle = clean_handle((at or prof).group(1))
            continue
        body.append(line)

    blocks: list[list[str]] = [[]]
    if any(_SEPARATOR_RE.match(line) for line in body):
        for line in body:
            if _SEPARATOR_RE.match(line):
                blocks.append([])
            else:
                blocks[-1].append(line)
    else:
        # No separators: each status URL opens a new post.
        for line in body:
            status = _STATUS_RE.search(line)
            if status and line.strip().strip("<>()[] ") == status.group(0) and any(
                _STATUS_RE.search(x) for x in blocks[-1]
            ):
                blocks.append([])
            blocks[-1].append(line)
    profile.posts = [p for p in (_text_block(b) for b in blocks if any(x.strip() for x in b)) if p]
    return [_finalize(profile)]


# ── Entry point ─────────────────────────────────────────────────────

def parse_payload(payload: str | dict[str, Any] | list[Any], default_star: str | None = None) -> list[XProfile]:
    """Parse an inject payload into profiles (one per star).

    ``default_star`` targets single-star payloads (the card the sheet was
    opened from); batch JSON names each star itself.
    """
    if isinstance(payload, (dict, list)):
        return _parse_json(payload, default_star)
    if not isinstance(payload, str) or not payload.strip():
        raise InjectError("empty payload")
    s = payload.strip()
    if s[0] in "{[":
        try:
            data = json.loads(s)
        except json.JSONDecodeError as exc:
            raise InjectError(f"invalid JSON: {exc.msg} (line {exc.lineno})") from None
        return _parse_json(data, default_star)
    if s.startswith("<") or "<article" in s or 'data-testid="' in s:
        return _parse_html(s, default_star)
    return _parse_text(s, default_star)
