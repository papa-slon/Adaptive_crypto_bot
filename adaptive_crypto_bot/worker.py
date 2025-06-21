"""Воркер: читает Redis-Stream с тиками и передаёт их стратегии."""
import asyncio, json, logging, redis.asyncio as redis         # type: ignore
from adaptive_crypto_bot.config import get_settings
from adaptive_crypto_bot.strategy.echo import EchoStrategy
from adaptive_crypto_bot.utils.logging import setup

log = setup()
S   = get_settings()

class DummySink:
    async def send(self, order): log.debug("ORDER %s", order)

async def main() -> None:
    r  = redis.Redis(host=S.REDIS_HOST, port=S.REDIS_PORT, decode_responses=True)
    st = EchoStrategy(DummySink())
    last_id = "$"

    while True:
        resp = await r.xread({S.REDIS_STREAM: last_id}, block=15_000, count=100)
        if not resp: continue
        for _, entries in resp:
            for _id, kv in entries:
                last_id = _id
                tick = {k: json.loads(v) if v.replace('.','',1).isdigit() else v
                        for k, v in kv.items()}
                await st.on_tick(tick)

if __name__ == "__main__":
    asyncio.run(main())
