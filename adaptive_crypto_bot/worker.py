"""Запускается в контейнере `bot`. Слушает Redis-стрим и прокидывает тики в стратегию."""
from __future__ import annotations
import asyncio, json, logging, os
import aioredis

from adaptive_crypto_bot.config      import get_settings
from adaptive_crypto_bot.strategy    import get as get_strategy
from adaptive_crypto_bot.services.executor import Executor
from adaptive_crypto_bot.utils.logging     import setup

log = setup("worker")
S   = get_settings()

async def _ticks():
    """Асинхронный генератор – бесконечно читает Redis Stream XREAD."""
    redis = aioredis.from_url(f"redis://{S.REDIS_HOST}:{S.REDIS_PORT}", decode_responses=True)
    last  = "$"
    while True:
        rows = await redis.xread({S.REDIS_STREAM: last}, block=10_000, count=100)
        if not rows:
            continue
        _, entries = rows[0]
        for _id, data in entries:
            last = _id
            yield json.loads(json.dumps(data))     # data   {'price': '...', ...}

async def main():
    strat_cls = get_strategy(os.getenv("STRATEGY", "dca"))
    strat     = strat_cls(Executor("BINANCE"))

    if hasattr(strat, "on_start"):
        await strat.on_start()

    async for tick in _ticks():
        await strat.on_tick(tick)

if __name__ == "__main__":
    asyncio.run(main())
