#!/usr/bin/env bash
set -euo pipefail

for f in /app/app.py /app/knowledge.py /app/classifier.py /app/reminder_worker.py; do
  if [ ! -r "$f" ]; then
    chmod 644 "$f" 2>/dev/null || true
    if [ ! -r "$f" ]; then
      echo "[entrypoint] ERROR: $f 不可读(bind mount 文件属主非当前用户)。" >&2
      echo "[entrypoint] 请在宿主机执行: chmod 644 $f" >&2
      exit 1
    fi
  fi
done

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
  echo "[entrypoint] starting kb_worker + reminder_worker (auto-reload on)"
  python -u - <<'PY' &
import os
import signal
import subprocess
import sys
import time

WATCHED = ('/app/app.py', '/app/knowledge.py', '/app/classifier.py', '/app/reminder_worker.py')
SCRIPTS = {'kb': 'knowledge.py', 'reminder': 'reminder_worker.py'}
INTERVAL = 1.0
stop = False


def _sig(_signum, _frame):
    global stop
    stop = True


signal.signal(signal.SIGTERM, _sig)
signal.signal(signal.SIGINT, _sig)


def _spawn(name):
    return subprocess.Popen([sys.executable, '-u', SCRIPTS[name]], cwd='/app')


procs = {name: _spawn(name) for name in SCRIPTS}
mtimes = {}
try:
    while not stop:
        time.sleep(INTERVAL)
        changed = [name for name, proc in procs.items() if proc.poll() is not None]
        for path in WATCHED:
            try:
                m = os.path.getmtime(path)
            except OSError:
                m = None
            if path in mtimes and m is not None and m != mtimes[path]:
                changed = [name for name, proc in procs.items()
                           if proc.poll() is None]
            mtimes[path] = m
        for name in set(changed):
            proc = procs[name]
            if proc.poll() is None:
                print('[reloader] code changed, restarting ' + name, flush=True)
                proc.terminate()
                try:
                    proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    proc.kill()
            procs[name] = _spawn(name)
finally:
    for _name, proc in procs.items():
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
PY
  WORKER_PID=$!
else
  echo "[entrypoint] starting kb_worker + reminder_worker"
  python knowledge.py &
  python reminder_worker.py &
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
