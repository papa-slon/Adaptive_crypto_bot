"""Простейшая ценовая Grid-стратегия."""
from __future__ import annotations
import logging

from adaptive_crypto_bot.strategy import register, BaseStrategy
from adaptive_crypto_bot.config   import get_settings

S   = get_settings()
log = logging.getLogger("GRID")

GRID_STEP_PCT = 0.2     # расстояние между уровнями, %

@register
class GridStrategy(BaseStrategy):
    async def on_start(self):
        log.info("GRID running (step %.2f%%).", GRID_STEP_PCT)

    async def on_tick(self, tick: dict):
        p = float(tick["price"])
        lvl = round(p / (1 + GRID_STEP_PCT/100), 2)
        if p < lvl:
            qty = round(S.SAFETY_ORDER_USDT / p, 6)
            await self.ex.buy(qty)
            log.debug("GRID-BUY %.4f @ %.2f", qty, p)
        else:
            qty = round(S.SAFETY_ORDER_USDT / p, 6)
            await self.ex.sell(qty)
            log.debug("GRID-SELL %.4f @ %.2f", qty, p)
