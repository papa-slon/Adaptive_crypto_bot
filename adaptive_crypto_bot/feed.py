"""Сервис-нормализатор: собирает тики с различных бирж и пишет в Redis Stream."""
import asyncio, json, redis.asyncio as redis          # type: ignore
from adaptive_crypto_bot.config import get_settings
from adaptive_crypto_bot.utils.logging import setup
from adaptive_crypto_bot.exchanges.binance import trade_socket as bin_ws
from adaptive_crypto_bot.exchanges.bingx   import trade_socket as bgx_ws

log = setup()
S   = get_settings()

async def writer():
    r = redis.Redis(host=S.REDIS_HOST, port=S.REDIS_PORT, decode_responses=True)
    async def push(socket):
        async for tick in socket():
            # фильтр защитный
            if 0 < tick["qty"] < 1e4:
                await r.xadd(S.REDIS_STREAM, tick, maxlen=500_000, approximate=True)
    await asyncio.gather(push(bin_ws), push(bgx_ws))

if __name__ == "__main__":
    asyncio.run(writer())
