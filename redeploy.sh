#!/bin/bash
# 代码/模板改动无需重建镜像(bind mount + 自动重载)。
# 依赖变化(requirements.txt / Dockerfile)时自动重建镜像以安装新依赖(如 fasttext)。
# up -d:compose 配置(.yaml/.env)变化时自动重建容器,否则沿用现有容器。
set -euo pipefail
cd "$(dirname "$0")"

IMAGE_NAME=$(docker-compose -f docker-compose.yaml config --images 2>/dev/null | head -1)
IMAGE_NAME="${IMAGE_NAME:-task-manager-app}"
NEEDS_BUILD=0
if ! docker image inspect "$IMAGE_NAME" >/dev/null 2>&1; then
  echo "[redeploy] 镜像 $IMAGE_NAME 不存在,先构建..."
  NEEDS_BUILD=1
else
  IMG_EPOCH=$(docker image inspect "$IMAGE_NAME" --format '{{.Created}}' | xargs -I{} date -d '{}' +%s 2>/dev/null || echo 0)
  for f in requirements.txt Dockerfile; do
    if [ -f "$f" ] && [ "$(stat -c %Y "$f")" -gt "$IMG_EPOCH" ]; then
      echo "[redeploy] $f 较新,重建镜像以安装新依赖..."
      NEEDS_BUILD=1
      break
    fi
  done
fi

if [ "$NEEDS_BUILD" = "1" ]; then
  docker-compose -f docker-compose.yaml build
fi

docker-compose -f docker-compose.yaml up -d
