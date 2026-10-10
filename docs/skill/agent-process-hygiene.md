# Agent Process Hygiene

> Date: 2026-10-10
> Rule: kill by PID only, detach long-lived processes with `setsid`, bound
> every wait with `timeout`, never build into the production output dir.

---

## Incidents (2026-10-10, frontend redesign session)

| What happened | Root cause |
|---|---|
| Shell call died with exit -1 mid-command | `pkill -f "nuxt dev --port 3100"` — the pattern also appears in the invoking shell's own command line, so it killed itself |
| Live site served broken assets until a restart | `nuxt build` in `frontend/` wipes and rewrites `.output`, which the running `xstream-frontend` serves from; an env-var override for the output dir was silently ignored |
| Dev server vanished; a screenshot run hung 150s until interrupted | Server started as `( npx nuxt dev ... &)` inside a foreground tool call — its lifetime was tied to that session; the probe script had no `timeout` |

## Rules

1. **Stop processes by PID, never by pattern.** Record `$!` to a PID file
   at start; before killing, check `/proc/$pid/cmdline` still matches (PID
   reuse). No `pkill -f` / `killall` / `pgrep -f | xargs kill`.
2. **Long-lived processes are detached**: `setsid nohup cmd > log 2>&1
   < /dev/null &`, or the tool's own background mode. Never `( cmd & )`
   inside a foreground call.
3. **Every wait is bounded**: `timeout N` around scripts, `curl
   --max-time`, poll loops with a max iteration count. Check the target is
   up before running a long probe against it.
4. **Never build into `frontend/.output` to test.** Preview with
   `scripts/preview_frontend.sh start|stop|status` (isolated copy under
   `/tmp/xstream-preview`, port 3100, setsid + PID file). Build in place only
   to deploy, immediately followed by `systemctl restart xstream-frontend`.
5. Prefer a production build preview over `nuxt dev` for screenshots — dev
   compiles routes on demand, so first loads are slow and flaky to time.
