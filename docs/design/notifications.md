# Outbound notifications (Telegram + tg-lint)

SSE pushes to browsers; **notify hooks** push selected events to Telegram for
operators (Grok bot / phone). Hooks share event **names** with SSE where both
apply; high-frequency SSE-only events are never hooks.

## Architecture

```text
publish_event(name, data)
    |
    +--> EventBus -> /api/events (browser)
    |
    +--> notify.schedule_dispatch
              |
              v
         render: tg-lint (HTML) | Python HTML fallback (always parse_mode=HTML)
              |
              v
         telegram.send_messages (split at 4096)
```

- **Registry**: `backend/services/notify/registry.py` — add a `NotifyHook` row
  to extend; no scattered string literals.
- **Formatter**: `tools/tg-lint` (Rust) reads JSON stdin, prints Telegram HTML.
- **Fallback**: `backend/services/notify/fallback.py` emits the same Telegram
  **HTML** shape if the binary is missing; `telegram.py` retries plain text only
  if Telegram rejects a chunk (`can't parse entities`).

### Telegram HTML practice (summary)

Official Bot API: set `parse_mode` to `HTML`; escape dynamic text (`&`, `<`, `>`);
use `<b>`, `<i>`, `<code>`, `<pre>`, `<blockquote>` / `<blockquote expandable>`,
and `<a href="…">` for links. See
[formatting options](https://core.telegram.org/bots/api#formatting-options).
tg-lint follows the operator-alert layout pattern: emoji + bold headline, labeled
rows (`<b>Label:</b> value`), blockquotes for lists and long errors.

Build tg-lint:

```bash
cd /root/xstream/tools/tg-lint && cargo build --release
```

Optional env override: `XSTREAM_TG_LINT=/path/to/tg-lint`.

## Configuration (`/etc/xstream.env`, never commit)

| Variable | Meaning |
|----------|---------|
| `XSTREAM_TELEGRAM_BOT_TOKEN` or `TELEGRAM_BOT_TOKEN` | BotFather token |
| `XSTREAM_TELEGRAM_CHAT_ID` or `TELEGRAM_CHAT_ID` | Your chat id |
| `XSTREAM_NOTIFY_EVENTS` | Comma list or `*`; default = hooks marked `default` in registry |
| `XSTREAM_NOTIFY_ENABLED` | `auto` (default), `0`, `1` |
| `XSTREAM_SYNC_INTERVAL_HOURS` | Scheduled title sync (default **4**) |
| `XSTREAM_TG_LINT` | Optional path to tg-lint binary |

Restart: `systemctl restart xstream-backend`.

Verify:

```bash
curl -s -b "xstream_auth=ok" https://<host>/api/notify/status | jq
curl -s -X POST -b "xstream_auth=ok" https://<host>/api/notify/test
```

## Hook catalog (event points)

| Event | Default | What you get |
|-------|---------|--------------|
| `sync.completed` | yes | **Per-star new works** — code, title, date, resolution, size |
| `sync.error` | yes | Sync failure |
| `metrics.alert` | yes | `play_timeout`, `play_error` from `/api/track` |
| `magnets.check_completed` | yes | alive / dead / swapped counts |
| `magnets.check_error` | yes | Check failure |
| `magnets.purged` | yes | TTL purge count |
| `sync.started` | no | Scheduler / manual start |
| `magnets.check_started` | no | Check start |
| `star.ready` | no | New star shelf |
| `star.social` / `creator.social` | no | X inject (enable via env if wanted) |

**Not hooks** (SSE only): `torrent.progress`, `files.changed`, `cache.update`, …

### Rich library updates

`scrapers/v2/tasks/sync_titles.py` attaches `new_titles[]` per star;
`sync.py` publishes `star_updates` on `sync.completed`. tg-lint renders
hierarchical HTML (star → bullet list of works).

### Metrics anomalies

`backend/routers/track.py` emits `metrics.alert` for `play_timeout` and
`play_error` (includes code, star_code, detail/meta). Triggers magnet recheck
for timeouts unchanged.

## Security

- Tokens only in `/etc/xstream.env` (600). Never log token or full message bodies.
- If a bot token was pasted in chat, **rotate via BotFather** and update env.
- `/api/notify/*` requires `xstream_auth` cookie.
