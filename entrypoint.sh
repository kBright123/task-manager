#!/usr/bin/env bash
set -euo pipefail

chmod 644 /app/app.py /app/knowledge.py 2>/dev/null || true

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

if [ "${KB_AUTO_RELOAD:-0}" = "1" ]; then
  echo "[entrypoint] starting kb_worker (auto-reload on)"
  python -u - <<'PY' &
import os
import signal
import subprocess
import sys
import time

WATCHED = ('/app/knowledge.py',)
INTERVAL = 1.0
stop = False


def _sig(_signum, _frame):
    global stop
    stop = True


signal.signal(signal.SIGTERM, _sig)
signal.signal(signal.SIGINT, _sig)


def _spawn():
    return subprocess.Popen([sys.executable, '-u', 'knowledge.py'], cwd='/app')


proc = _spawn()
mtimes = {}
try:
    while not stop:
        time.sleep(INTERVAL)
        changed = proc.poll() is not None
        for path in WATCHED:
            try:
                m = os.path.getmtime(path)
            except OSError:
                m = None
            if path in mtimes and m is not None and m != mtimes[path]:
                changed = True
            mtimes[path] = m
        if not changed:
            continue
        if proc.poll() is None:
            print('[reloader] code changed, restarting kb_worker', flush=True)
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
        else:
            print('[reloader] kb_worker exited, restarting', flush=True)
        proc = _spawn()
finally:
    if proc.poll() is None:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
PY
  WORKER_PID=$!
else
  echo "[entrypoint] starting kb_worker"
  python knowledge.py &
  WORKER_PID=$!
fi

cleanup() {
  echo "[entrypoint] shutting down"
  kill "$WORKER_PID" 2>/dev/null || true
  kill "$SOCHDB_PID" 2>/dev/null || true
}
trap cleanup EXIT TERM INT

GUNICORN_ARGS="--bind 0.0.0.0:5000 --workers 4 --timeout 120"
if [ "${KB_AUTO_RELOAD:-0}" = "1" ]; then
  GUNICORN_ARGS="$GUNICORN_ARGS --reload"
fi

echo "[entrypoint] starting gunicorn"
exec gunicorn $GUNICORN_ARGS app:app
