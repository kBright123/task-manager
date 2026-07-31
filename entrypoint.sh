#!/usr/bin/env bash
set -euo pipefail

SOCHDB_PATH="${KB_SOCHDB_PATH:-/app/instance/kb_data/kb.soch}"
mkdir -p "$(dirname "$SOCHDB_PATH")"

SOCHDB_BIN=$(python -c \
  "import glob, os, sochdb; print(glob.glob(os.path.join(sochdb.__path__[0], '_bin', '*', 'sochdb-server'))[0])")

echo "[entrypoint] starting sochdb-server (db=$SOCHDB_PATH)"
"$SOCHDB_BIN" --db "$SOCHDB_PATH" --log-level info &
SOCHDB_PID=$!

SOCK="$SOCHDB_PATH/sochdb.sock"
for _ in $(seq 1 60); do
  [ -S "$SOCK" ] && break
  sleep 0.5
done
if [ ! -S "$SOCK" ]; then
  echo "[entrypoint] ERROR: sochdb-server socket not ready" >&2
  kill "$SOCHDB_PID" 2>/dev/null || true
  exit 1
fi
echo "[entrypoint] sochdb-server ready"

echo "[entrypoint] starting kb_worker"
python -m kb.worker &
WORKER_PID=$!

cleanup() {
  echo "[entrypoint] shutting down"
  kill "$WORKER_PID" 2>/dev/null || true
  kill "$SOCHDB_PID" 2>/dev/null || true
}
trap cleanup EXIT TERM INT

echo "[entrypoint] starting gunicorn"
exec gunicorn --bind 0.0.0.0:5000 --workers 4 --timeout 120 app:app
