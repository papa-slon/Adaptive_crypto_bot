import asyncio, logging
from adaptive_crypto_bot.logging_setup import setup
log = setup()

class RiskManager:
    async def run(self):
        while True:
            log.debug("[RiskManager] heartbeat")
            await asyncio.sleep(7)
