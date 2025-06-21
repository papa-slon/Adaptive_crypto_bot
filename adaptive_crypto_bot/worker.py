"""Worker-консьюмер: Redis → стратегия (DCA)."""
import asyncio, redis.asyncio as redis          # type: ignore
from adaptive_crypto_bot.config   import get_settings
from adaptive_crypto_bot.utils.logging import setup
from adaptive_crypto_bot.strategy.dca import DCAStrategy
from adaptive_crypto_bot.services.executor import Executor

log = setup()
S   = get_settings()

GROUP   = "bot"
CONSUMER= "worker-1"

async def main():
    r = redis.Redis(host=S.REDIS_HOST, port=S.REDIS_PORT, decode_responses=True)
    try:
        await r.xgroup_create(name=S.REDIS_STREAM, groupname=GROUP, id="0-0", mkstream=True)
    except redis.ResponseError:
        pass  # group exists

    strat = DCAStrategy(Executor("BINANCE"))

    while True:
        resp = await r.xreadgroup(GROUP, CONSUMER, streams={S.REDIS_STREAM: ">"}, count=100, block=5000)
        if not resp: continue
        _, msgs = resp[0]
        ticks = [m[1] for m in msgs]
        await strat.on_ticks(ticks)

if __name__ == "__main__":
    asyncio.run(main())
