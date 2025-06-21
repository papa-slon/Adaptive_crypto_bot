"""Асинхронный репозиторий: читаем/пишем X-stream в Redis."""
import os
import redis.asyncio as aioredis
from typing import Dict, Any, List

STREAM_KEY = os.getenv("REDIS_STREAM", "ticks:core")

class RedisRepo:
    def __init__(self, host: str = "redis", port: int = 6379) -> None:
        self._r = aioredis.Redis(host=host, port=port, decode_responses=True)

    # ───────── streams (pub) ────────────────────────────────────────────────────
    async def publish_tick(self, data: Dict[str, Any]) -> None:
        """XADD ticks stream (MAXLEN ~500k, ~1day истории)."""
        await self._r.xadd(STREAM_KEY, data, maxlen=500_000, approximate=True)

    # ───────── streams (sub) ────────────────────────────────────────────────────
    async def listen_ticks(self, last_id: str = "$"):
        """Асинхронно читаем новые элементы XREAD."""
        while True:
            resp = await self._r.xread({STREAM_KEY: last_id}, block=0, count=100)
            if not resp:
                continue
            _, entries = resp[0]
            for entry_id, data in entries:
                last_id = entry_id
                yield data
