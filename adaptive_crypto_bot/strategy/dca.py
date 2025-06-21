"""DCA-стратегия: каждые N USDT покупаем фиксированный объём BTC."""
from __future__ import annotations
import asyncio, logging, math
from decimal import Decimal, ROUND_DOWN
from adaptive_crypto_bot.config import get_settings
from adaptive_crypto_bot.utils.logging import setup
from .base import BaseStrategy, Exchange

S   = get_settings()
log = setup()

USDT_STEP = Decimal(str(S.BASE_ORDER_USDT))           # step in USDT

class DCAStrategy(BaseStrategy):
    def __init__(self, exch: Exchange):
        super().__init__(exch)
        self._accum: Decimal = Decimal("0")

    async def on_tick(self, tick: dict[str, float]):                # noqa: D401
        price = Decimal(str(tick["price"]))
        self._accum += Decimal(str(tick["qty"])) * price

        if self._accum >= USDT_STEP:
            # сколько BTC на USDT_STEP?
            qty = (USDT_STEP / price).quantize(Decimal("0.000001"), ROUND_DOWN)
            self._accum -= USDT_STEP
            log.info("DCA BUY %.6f BTC @ %.2f", float(qty), float(price))
            try:
                await self.exch.new_order("BUY", float(qty))
            except Exception as e:
                log.exception("order error: %s", e)
                # вернём накопление обратно — повторим позже
                self._accum += USDT_STEP
