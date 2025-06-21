#!/usr/bin/env bash
set -euo pipefail
python - <<'PY'
import asyncio, os, redis, sys, aiohttp
async def ok():
    # Redis
    r = redis.Redis(host=os.getenv("REDIS_HOST","redis"), port=6379)
    r.ping()
    # Binance ping
    async with aiohttp.ClientSession() as s:
        async with s.get("https://api.binance.com/api/v3/ping", timeout=4) as r:
            if r.status!=200: raise SystemExit(1)
asyncio.run(ok())
PY
