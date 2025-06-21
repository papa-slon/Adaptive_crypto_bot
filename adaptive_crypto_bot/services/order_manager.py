import asyncio, logging
from adaptive_crypto_bot.logging_setup import setup
log = setup()

class OrderManager:
    async def run(self):
        while True:
            log.debug("[OrderManager] heartbeat")
            await asyncio.sleep(5)
