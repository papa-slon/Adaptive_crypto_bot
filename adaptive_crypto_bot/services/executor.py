"""Абстракция над биржевыми клиентами.  Стратегии дергают buy/sell – дальше магия."""
from __future__ import annotations
import logging, asyncio

from adaptive_crypto_bot.exchanges import get_client
from adaptive_crypto_bot.utils.logging import setup

log = setup("Executor")

class Executor:
    def __init__(self, venue: str) -> None:
        client_cls = get_client(venue)
        self._cli  = client_cls()
        self._lock = asyncio.Lock()

    # стратегии не должны сломать клиента параллельными запросами
    async def _exec(self, *a, **k):
        async with self._lock:
            return await self._cli.new_order(*a, **k)

    # ─────────────────── публичный API для стратегий ───────────────────
    async def buy(self, qty: float, price: float | None = None):
        log.debug("BUY %.4f @ %s", qty, f"{price:.2f}" if price else "MKT")
        return await self._exec("BUY", qty, price)

    async def sell(self, qty: float, price: float | None = None):
        log.debug("SELL %.4f @ %s", qty, f"{price:.2f}" if price else "MKT")
        return await self._exec("SELL", qty, price)
