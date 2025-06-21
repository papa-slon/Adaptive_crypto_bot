"""Executor: единый интерфейс для стратегий (place/cancel, get_depth …)."""
from __future__ import annotations
import logging, asyncio

from adaptive_crypto_bot.utils.logging   import setup
from adaptive_crypto_bot.exchanges       import get_client

log = setup("executor")

class Executor:
    """Унифицирует работу со всеми поддерживаемыми биржами.

    Пример:
        ex = Executor("BINANCE")
        await ex.buy(0.001, price=30000)
    """

    def __init__(self, venue: str) -> None:
        self.venue   = venue.upper()
        self._client = get_client(self.venue)

    # ───────────────────────────── wrappers
    async def buy(self, qty: float, price: float | None = None):
        log.debug("BUY %s %s @ %s", self.venue, qty, price)
        return await self._client.new_order("BUY", qty, price)

    async def sell(self, qty: float, price: float | None = None):
        log.debug("SELL %s %s @ %s", self.venue, qty, price)
        return await self._client.new_order("SELL", qty, price)

    async def cancel_all(self):
        log.debug("CANCEL-ALL %s", self.venue)
        return await self._client.cancel_all()

    async def depth(self, limit: int = 5):
        return await self._client.get_depth(limit)

    # ───────────────────────────── graceful close
    async def close(self):
        close = getattr(self._client, "close", None)
        if asyncio.iscoroutinefunction(close):
            await close()
