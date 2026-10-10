#!/usr/bin/env bash
# Preview the working-tree frontend on its own port without touching
# production. Production serves frontend/.output, and `nuxt build` wipes and
# rewrites that directory, so building in place breaks the live site until
# a restart. This builds an isolated copy under $PREVIEW_DIR instead.
#
#   scripts/preview_frontend.sh start   # build copy + serve on $PREVIEW_PORT
#   scripts/preview_frontend.sh stop
#   scripts/preview_frontend.sh status
#
# The server runs under setsid (detached from the calling shell) and is
# stopped only via its PID file — never by pattern (pkill -f matches the
# invoking shell's own command line).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PREVIEW_DIR="${PREVIEW_DIR:-/tmp/xstream-preview}"
PREVIEW_PORT="${PREVIEW_PORT:-3100}"
PID_FILE="$PREVIEW_DIR.pid"
LOG_FILE="$PREVIEW_DIR.log"
BUILD_LOG="$PREVIEW_DIR.build.log"
SERVER="$PREVIEW_DIR/.output/server/index.mjs"

is_ours() {
  # PID alive AND still our server (guards against PID reuse).
  local pid="$1"
  [[ -r "/proc/$pid/cmdline" ]] && tr '\0' ' ' < "/proc/$pid/cmdline" | grep -qF "$SERVER"
}

stop() {
  if [[ -f "$PID_FILE" ]]; then
    local pid
    pid="$(cat "$PID_FILE")"
    if is_ours "$pid"; then
      kill "$pid"
      for _ in $(seq 1 20); do is_ours "$pid" || break; sleep 0.25; done
      echo "stopped preview (pid $pid)"
    fi
    rm -f "$PID_FILE"
  else
    echo "no preview running"
  fi
}

status() {
  if [[ -f "$PID_FILE" ]] && is_ours "$(cat "$PID_FILE")"; then
    echo "running: pid $(cat "$PID_FILE"), http://127.0.0.1:$PREVIEW_PORT"
  else
    echo "not running"
  fi
}

start() {
  stop >/dev/null
  mkdir -p "$PREVIEW_DIR"
  (cd "$ROOT/frontend" && tar --exclude=./node_modules --exclude=./.output --exclude=./.nuxt -cf - .) \
    | tar -xf - -C "$PREVIEW_DIR"
  ln -sfn "$ROOT/frontend/node_modules" "$PREVIEW_DIR/node_modules"

  echo "building into $PREVIEW_DIR (log: $BUILD_LOG)..."
  if ! (cd "$PREVIEW_DIR" && timeout 600 npx nuxt build > "$BUILD_LOG" 2>&1); then
    tail -30 "$BUILD_LOG"
    exit 1
  fi

  NITRO_HOST=127.0.0.1 NITRO_PORT="$PREVIEW_PORT" \
    setsid nohup node "$SERVER" > "$LOG_FILE" 2>&1 < /dev/null &
  echo $! > "$PID_FILE"

  for _ in $(seq 1 40); do
    if curl -s -o /dev/null --max-time 2 "http://127.0.0.1:$PREVIEW_PORT/login"; then
      echo "preview up: http://127.0.0.1:$PREVIEW_PORT (pid $(cat "$PID_FILE"))"
      return
    fi
    sleep 0.5
  done
  echo "preview did not come up; see $LOG_FILE" >&2
  exit 1
}

case "${1:-}" in
  start) start ;;
  stop) stop ;;
  status) status ;;
  *) echo "usage: $0 {start|stop|status}" >&2; exit 2 ;;
esac
