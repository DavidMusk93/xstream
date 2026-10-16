# Agent Process Hygiene

> Date: 2026-10-10
> Rule: kill by PID only, run anything longer than ~20s as a transient
> systemd unit (`systemd-run`), keep each tool call short and poll, never
> build into the production output dir in the foreground.

---

## Incidents (2026-10-10, frontend redesign session)

| What happened | Root cause |
|---|---|
| Shell call died with exit -1 mid-command | `pkill -f "nuxt dev --port 3100"` — the pattern also appears in the invoking shell's own command line, so it killed itself |
| Live site served broken assets until a restart | `nuxt build` in `frontend/` wipes and rewrites `.output`, which the running `xstream-frontend` serves from; an env-var override for the output dir was silently ignored |
| Dev server vanished; a screenshot run hung 150s until interrupted | Server started as `( npx nuxt dev ... &)` inside a foreground tool call — its lifetime was tied to that session; the probe script had no `timeout` |
| Live site returned 500 for ~15 min (2026-10-10) | A foreground `nuxt build && systemctl restart` was interrupted after it had wiped `.output` but before Nitro finished; low free RAM (~0.9 GB) had stretched the build from ~45s to 4 min |
| Detached (`setsid nohup`) preview build silently vanished (2026-10-15) | An interrupt tears down the tool call's whole cgroup; `setsid` leaves the session but not the cgroup. No OOM in the kernel log |

## Rules

1. **Stop processes by PID, never by pattern.** Record `$!` to a PID file
   at start; before killing, check `/proc/$pid/cmdline` still matches (PID
   reuse). No `pkill -f` / `killall` / `pgrep -f | xargs kill`.
2. **Anything that must survive an interrupt runs as a transient unit**:
   `systemd-run --unit=NAME --collect --working-directory=DIR
   --setenv=PATH="$PATH" bash -c 'cmd > log 2>&1; echo "done=$?" >> log'`.
   Add `-p KillMode=process` when the command leaves a server behind
   (e.g. `preview_frontend.sh start`), or systemd reaps it when the main
   process exits. `setsid nohup` is not enough (same cgroup). Never
   `( cmd & )` inside a foreground call.
   Then poll the log with short calls (≤ 10s each) — a long blocking wait
   is itself the thing that gets interrupted.
3. **Every wait is bounded**: `timeout N` around scripts, `curl
   --max-time`, poll loops with a max iteration count. Check the target is
   up before running a long probe against it.
4. **Never build into `frontend/.output` to test.** Preview with
   `scripts/preview_frontend.sh start|stop|status` (isolated copy under
   `/tmp/xstream-preview`, port 3100, setsid + PID file). Build in place only
   to deploy — inside a `systemd-run` unit, chained with `systemctl restart
   xstream-frontend` — and stop the preview first to free RAM.
5. Prefer a production build preview over `nuxt dev` for screenshots — dev
   compiles routes on demand, so first loads are slow and flaky to time.
