#!/usr/bin/env bash
# Install and start an omesh worker node on cc2 or racknerd.
# Downloads the compiled omesh binary from ostore (bin/omesh), writes /etc/omesh.env,
# and enables omesh.service on :8767.
#
# Usage (run on cc2 or rn):
#   OMESH_NODE_ID=rn OSTORE_URL=http://203.88.122.188:8781 OSTORE_TOKEN=... bash install-omesh-worker.sh

set -euo pipefail

NODE_ID="${OMESH_NODE_ID:?set OMESH_NODE_ID (e.g. cc2 or rn)}"
OSTORE_URL="${OSTORE_URL:?set OSTORE_URL (e.g. http://127.0.0.1:8783 or cc ostore URL)}"
OSTORE_TOKEN="${OSTORE_TOKEN:?set OSTORE_TOKEN}"
BIND="${OMESH_BIND:-0.0.0.0:8767}"
PEERS="${OMESH_PEERS:-}"
BT_URL="${OMESH_BT_URL:-}"

install -d /usr/local/bin /var/tmp/omesh-work
echo "[omesh] Downloading binary from ${OSTORE_URL}/api/files/bin/omesh ..."
curl -fsSL -H "Authorization: Bearer ${OSTORE_TOKEN}" \
  "${OSTORE_URL}/api/files/bin/omesh" -o /usr/local/bin/omesh.new
chmod +x /usr/local/bin/omesh.new
mv /usr/local/bin/omesh.new /usr/local/bin/omesh

cat >/etc/omesh.env <<EOF
OMESH_NODE_ID=${NODE_ID}
OMESH_BIND=${BIND}
OMESH_TOKEN=${OSTORE_TOKEN}
OMESH_OSTORE_URL=${OSTORE_URL}
OMESH_OSTORE_TOKEN=${OSTORE_TOKEN}
OMESH_WORK_DIR=/var/tmp/omesh-work
OMESH_PEERS=${PEERS}
OMESH_BT_URL=${BT_URL}
EOF
chmod 600 /etc/omesh.env

cat >/etc/systemd/system/omesh.service <<'EOF'
[Unit]
Description=omesh Compute & HTTP Range CDN Worker
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
EnvironmentFile=/etc/omesh.env
Environment=RUST_LOG=omesh=info
ExecStart=/usr/local/bin/omesh
Restart=on-failure
RestartSec=3s
User=root
LimitNOFILE=65536

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable --now omesh.service
sleep 1
curl -fsS http://127.0.0.1:8767/health
echo ""
echo "[omesh] Worker ${NODE_ID} is active on ${BIND}"
