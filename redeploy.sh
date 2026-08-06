#!/bin/bash
# 代码/模板改动无需重建镜像(bind mount + 自动重载)。
# up -d:compose 配置(.yaml/.env)变化时自动重建容器,否则沿用现有容器。
docker-compose -f docker-compose.yaml up -d
