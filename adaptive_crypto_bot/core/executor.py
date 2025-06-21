"""Абстракция для размещения/отмены ордеров независимо от биржи."""

import asyncio, logging
from typing import Dict, Any

from adaptive_crypto_bot.config import get_settings
from adaptive_crypto_bot.core.models import Order, Side

from adaptive_crypto_bot.exchanges.binance import BinanceClient
from adaptive_crypto_bot.exchanges.bingx   import BingXClient

cfg = get_settings()
_LOG = logging.getLogger("exec")

class OrderExecutor:
    def __init__(self) -> None:
        self.bin = BinanceClient(cfg.BINANCE_API_KEY, cfg.BINANCE_SECRET, cfg.SYMBOL)
        self.bgx = BingXClient  (cfg.BINGX_API_KEY, cfg.BINGX_SECRET, cfg.SYMBOL.replace("USDT", "USDT"))

    async def place_order(self, side: Side, qty: float, price: float) -> Order:
        # сейчас используем только Binance, можно сделать router позже
        resp = await self.bin.create_order(side, qty, price)
        return Order(
            order_id   = resp["orderId"],
            symbol     = resp["symbol"],
            side       = side,
            qty        = float(resp["origQty"]),
            price      = float(resp["price"]),
            status     = resp["status"],
            exchange   = "binance",
            created_at = cfg.now(),
        )

    async def shutdown(self):
        await asyncio.gather(self.bin.close(), self.bgx.close())
