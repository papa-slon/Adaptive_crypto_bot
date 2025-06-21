#!/usr/bin/env bash
set -euo pipefail
python - <<'PY'
import sys, os, redis
host = os.getenv("REDIS_HOST", "redis")
try:
    redis.Redis(host=host, port=6379, socket_connect_timeout=1).ping()
    sys.exit(0)
except Exception:
    sys.exit(1)
PY
