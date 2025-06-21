"""Главный event-loop → запускается из run.py."""

import asyncio, logging
from adaptive_crypto_bot.config           import get_settings
from adaptive_crypto_bot.core.repository  import RedisRepo
from adaptive_crypto_bot.core.strategy    import DcaStrategy
from adaptive_crypto_bot.core.executor    import OrderExecutor

cfg = get_settings()
logging.basicConfig(
    level=cfg.LOG_LEVEL,
    format="%(asctime)s  %(levelname)s  %(name)s ▶ %(message)s",
)

async def main():
    repo      = RedisRepo(cfg.REDIS_HOST, cfg.REDIS_PORT)
    strategy  = DcaStrategy()
    executor  = OrderExecutor()

    try:
        async for tick in repo.listen_ticks():
            await strategy.on_tick(tick, executor)
    finally:
        await executor.shutdown()

if __name__ == "__main__":
    asyncio.run(main())
