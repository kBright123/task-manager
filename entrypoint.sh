#!/usr/bin/env bash

# This file is part of 知行合一 · 任务与知识管理系统 (TaskManager).
# Copyright (C) 2026 TaskManager contributors
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <https://www.gnu.org/licenses/>.

set -euo pipefail

# ===== 后台安装系统依赖（不影响服务启动） =====
install_deps() {
    if [ -f /usr/lib/x86_64-linux-gnu/libglib-2.0.so.0 ]; then
        echo "[entrypoint] System dependencies already installed, skipping." >> /app/deps_install.log
        return 0
    fi

    echo "[entrypoint] Installing system dependencies in background..." >> /app/deps_install.log
    # 换阿里云源（可自行调整）
    echo "deb https://mirrors.aliyun.com/debian bookworm main contrib non-free non-free-firmware" > /etc/apt/sources.list && \
    echo "deb https://mirrors.aliyun.com/debian bookworm-updates main contrib non-free non-free-firmware" >> /etc/apt/sources.list && \
    echo "deb https://mirrors.aliyun.com/debian-security bookworm-security main contrib non-free non-free-firmware" >> /etc/apt/sources.list && \
    apt-get update -o Acquire::http::Show-Progress=true && \
    apt-get install -y --no-install-recommends --verbose-versions -o Acquire::http::Show-Progress=true \
        libglib2.0-0 libgl1 libgomp1 && \
    rm -rf /var/lib/apt/lists/* && \
    echo "[entrypoint] System dependencies installed." >> /app/deps_install.log
}

install_deps &

# ===== 权限修复（针对挂载文件） =====
# bind mount 的文件保留宿主属主/权限。若容器内以 root 运行仍不可读, 通常是
# rootless/podman 或 userns-remap(容器 root ≠ 宿主 root), 容器内 chown/chmod
# 对宿主文件无效, 必须回到宿主机处理。
for f in /app/app.py /app/knowledge.py /app/classifier.py /app/reminder_worker.py /app/notes.py /app/job_worker.py /app/backup.py /app/routes_admin.py /app/routes_auth.py /app/routes_tasks.py /app/routes_search.py /app/routes_notify.py; do
  if [ ! -r "$f" ]; then
    chown appuser:appuser "$f" 2>/dev/null || true
    chmod 644 "$f" 2>/dev/null || true
    if [ ! -r "$f" ]; then
      echo "[entrypoint] ERROR: $f 不可读(容器内 root 无权修改该 bind mount 文件)。" >&2
      ls -ln "$f" >&2 2>/dev/null || true
      echo "[entrypoint] 请在宿主机执行: chmod 644 $f" >&2
      echo "[entrypoint] (rootless/podman 或 userns-remap 时容器 root ≠ 宿主 root, 容器内 chown/chmod 无效)" >&2
      exit 1
    fi
  fi
done

# ===== instance 数据目录（bind mount 自宿主，属主可能是 root） =====
if [ -d /app/instance ]; then
  chown -R appuser:appuser /app/instance 2>/dev/null || true
  chmod -R u+rwX /app/instance 2>/dev/null || true
fi

# ===== backups 备份目录（bind mount 自宿主） =====
mkdir -p /app/backups 2>/dev/null || true
chown appuser:appuser /app/backups 2>/dev/null || true
chmod 700 /app/backups 2>/dev/null || true

# ===== sochdb-server（向量数据库） =====
if [ "${KB_VECTOR_DISABLED:-0}" = "1" ]; then
  echo "[entrypoint] KB_VECTOR_DISABLED=1, skipping sochdb-server (vector DB)"
  SOCHDB_PID=""
else
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
fi

# ===== 启动 Workers（使用 su appuser -c 切换，不带 - 避免 login shell 问题） =====
export HOME=/home/appuser
KB_WORKER_ENABLED="${KB_WORKER_ENABLED:-1}"
REMINDER_WORKER_ENABLED="${REMINDER_WORKER_ENABLED:-1}"
JOB_WORKER_ENABLED="${JOB_WORKER_ENABLED:-1}"

if [ "${KB_AUTO_RELOAD:-0}" = "1" ]; then
  echo "[entrypoint] starting kb_worker + reminder_worker + job_worker (auto-reload on)"
  su appuser -c "python -u - <<'PY'
import os
import signal
import subprocess
import sys
import time

WATCHED = ('/app/app.py', '/app/knowledge.py', '/app/classifier.py', '/app/reminder_worker.py', '/app/notes.py', '/app/job_worker.py', '/app/routes_admin.py', '/app/routes_auth.py', '/app/routes_tasks.py', '/app/routes_search.py', '/app/routes_notify.py')
SCRIPTS = {k: v for k, v in {
    'kb': ('knowledge.py', 'KB_WORKER_ENABLED'),
    'reminder': ('reminder_worker.py', 'REMINDER_WORKER_ENABLED'),
    'job': ('job_worker.py', 'JOB_WORKER_ENABLED'),
}.items() if os.environ.get(v[1], '1') == '1'}
SCRIPTS = {k: v[0] for k, v in SCRIPTS.items()}
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
PY" &
  WORKER_PID=$!
else
  echo "[entrypoint] starting background workers (kb=${KB_WORKER_ENABLED} reminder=${REMINDER_WORKER_ENABLED} job=${JOB_WORKER_ENABLED})"
  WORKER_PIDS=()
  if [ "${KB_WORKER_ENABLED:-1}" = "1" ]; then
    su appuser -c "python knowledge.py" &
    WORKER_PIDS+=("$!")
  fi
  if [ "${REMINDER_WORKER_ENABLED:-1}" = "1" ]; then
    su appuser -c "python reminder_worker.py" &
    WORKER_PIDS+=("$!")
  fi
  if [ "${JOB_WORKER_ENABLED:-1}" = "1" ]; then
    su appuser -c "python job_worker.py" &
    WORKER_PIDS+=("$!")
  fi
fi

# ===== 清理函数 =====
cleanup() {
  echo "[entrypoint] shutting down"
  for _pid in "${WORKER_PIDS[@]:-}"; do kill "$_pid" 2>/dev/null || true; done
  if [ "${KB_AUTO_RELOAD:-0}" = "1" ]; then kill "$WORKER_PID" 2>/dev/null || true; fi
  kill "$SOCHDB_PID" 2>/dev/null || true
}
trap cleanup EXIT TERM INT

# ===== 启动 Gunicorn（以 appuser 运行） =====
GUNICORN_ARGS="--bind 0.0.0.0:5000 --workers 2 --threads 4 --timeout 120 --max-requests 1200 --max-requests-jitter 150"
if [ "${KB_AUTO_RELOAD:-0}" = "1" ]; then
  GUNICORN_ARGS="$GUNICORN_ARGS --reload"
fi

echo "[entrypoint] starting gunicorn"
exec su appuser -c "gunicorn $GUNICORN_ARGS app:app"
