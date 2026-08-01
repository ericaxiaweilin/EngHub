#!/bin/sh
set -eu

# 尝试迁移，失败不阻塞启动
python /app/scripts/schema_migrate.py || echo "[entrypoint] schema migration failed, continuing..."

exec "$@"
