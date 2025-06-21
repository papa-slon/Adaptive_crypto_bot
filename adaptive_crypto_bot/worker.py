"""Worker: читает поток тиков из Redis и отдаёт их выбранной стратегии.

Стратегия задаётся переменной окружения/конфига **STRATEGY**
(например, GRID, DCA, SCALP и т.д.).  По умолчанию – DCA.
"""
from __future__ import annotations

import asyncio, importlib, logging, redis.asyncio as redis

from adaptive_crypto_bot.config          import get_settings
from adaptive_crypto_bot.services.executor import Executor          # ← ваш REST/WS обёртки
from adaptive_crypto_bot.utils.logging   import setup

S   = get_settings()
log = setup("worker")

# ───────────────────────────── стратегия динамически
def _load_strategy():
    name = getattr(S, "STRATEGY", "DCA").lower()          # dca / grid …
    mod  = importlib.import_module(f"adaptive_crypto_bot.strategy.{name}")
    cls  = next(getattr(mod, c) for c in dir(mod) if c.lower().startswith(name))
    return cls                                            # type: ignore[return-value]

StrategyCls = _load_strategy()
strategy    = StrategyCls(Executor("BINANCE"))

# ───────────────────────────── consumer
async def consume():
    r: redis.Redis = redis.Redis(host=S.REDIS_HOST, port=S.REDIS_PORT,
                                 decode_responses=True)
    last_id = "0"
    while True:
        try:
            resp = await r.xread({S.REDIS_STREAM: last_id}, count=100, block=1000)
            if not resp:
                continue
            for _, msgs in resp:
                for _id, data in msgs:
                    await strategy.on_tick(data)          # передаём тик стратегии
                    last_id = _id
        except Exception as e:
            log.exception("consume-loop error: %s", e)
            await asyncio.sleep(1)

# ───────────────────────────── entry-point
async def main():
    # если у стратегии есть фоновые задачи – запустим
    bg = getattr(strategy, "run_background", None)
    await asyncio.gather(*(f() for f in ([consume] if bg is None else [consume, bg])))

if __name__ == "__main__":
    asyncio.run(main())
