# syntax=docker/dockerfile:1
FROM python:3.11-slim

WORKDIR /app

ENV PYTHONUNBUFFERED=1 \
    HF_ENDPOINT=https://hf-mirror.com \
    HF_HUB_DISABLE_XET=1 \
    HF_HOME=/app/hf_cache

# ===== 1. 先复制依赖文件并安装（利用 Docker 层缓存） =====
COPY requirements.txt .
RUN pip config set global.index-url https://pypi.tuna.tsinghua.edu.cn/simple \
    && pip install --no-cache-dir -r requirements.txt

# ===== 2. 复制剩余代码 =====
COPY . .

# ===== 3. 创建非 root 用户（带有效 home 和 shell，以便 su 切换使用） =====
RUN mkdir -p /home/appuser && \
    addgroup --system appuser && \
    adduser --system --ingroup appuser --home /home/appuser --shell /bin/bash appuser && \
    chown -R appuser:appuser /home/appuser

# ===== 4. 设置文件权限（确保 appuser 可读所有代码，entrypoint.sh 可执行） =====
RUN chown -R appuser:appuser /app && \
    find /app -type d -exec chmod 755 {} \; && \
    find /app -type f -exec chmod 644 {} \; && \
    chmod +x /app/entrypoint.sh

# ===== 5. 创建持久化数据目录 =====
RUN mkdir -p /app/instance/kb_data /app/instance/uploads /app/hf_cache && \
    chown -R appuser:appuser /app/instance /app/hf_cache

EXPOSE 5000

# 保持 root 运行 entrypoint，由 entrypoint 内部切换用户
ENTRYPOINT ["bash", "/app/entrypoint.sh"]
