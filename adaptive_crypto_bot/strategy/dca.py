"""Классическая DCA-усреднялка (MartinGale light)."""
from __future__ import annotations
import math, logging

from adaptive_crypto_bot.strategy import register, BaseStrategy
from adaptive_crypto_bot.config   import get_settings

S   = get_settings()
log = logging.getLogger("DCA")

@register
class DCAStrategy(BaseStrategy):
    """Документация алгоритма внутри кода."""

    async def on_start(self):
        log.info("DCA strategy started for %s.", S.SYMBOL)

    async def on_tick(self, tick: dict):
        # простейшая логика: через каждые N тиков покупаем BASE_ORDER_USDT
        if tick["src"] == "BIN":           # чтобы не срабатывать на всех потоках
            price = float(tick["price"])
            qty   = round(S.BASE_ORDER_USDT / price, 6)
            await self.ex.buy(qty)
            log.debug("BUY %.4f @ %.2f", qty, price)
