#!/bin/bash
set -euo pipefail

export DISPLAY=:99

pids=()
cleanup() {
    kill "${pids[@]}" 2>/dev/null || true
    wait "${pids[@]}" 2>/dev/null || true
}
trap cleanup EXIT

Xvfb "$DISPLAY" -screen 0 1600x900x24 -nolisten tcp &
pids+=("$!")

for _ in {1..50}; do
    if xdpyinfo >/dev/null 2>&1; then
        break
    fi
    sleep 0.1
done
xdpyinfo >/dev/null

openbox &
pids+=("$!")

install -d -m 700 /root/.vnc/chrome-profile
/root/.cache/ms-playwright/chromium-1148/chrome-linux/chrome \
    --no-sandbox \
    --disable-dev-shm-usage \
    --disable-gpu \
    --no-first-run \
    --no-default-browser-check \
    --disable-session-crashed-bubble \
    --start-maximized \
    --user-data-dir=/root/.vnc/chrome-profile \
    about:blank &
pids+=("$!")

x11vnc \
    -display "$DISPLAY" \
    -rfbauth /root/.vnc/passwd \
    -rfbport 5900 \
    -localhost \
    -shared \
    -forever \
    -wait 33 \
    -defer 20 \
    -wait_ui 2 \
    -setdefer -1 \
    -readtimeout 60 \
    -ping 30 &
pids+=("$!")

websockify \
    --web /usr/share/novnc \
    --heartbeat=30 \
    6080 localhost:5900 &
pids+=("$!")

wait -n "${pids[@]}"
