"""Роутер ордеров: абстрагирует конкретную биржу для стратегии."""
from __future__ import annotations
import asyncio
from typing import Literal, Mapping, Any
from adaptive_crypto_bot.exchanges.binance import BinanceREST
from adaptive_crypto_bot.exchanges.bingx   import BingXREST
from adaptive_crypto_bot.utils.logging     import setup

log = setup()

_EXCH: dict[str, Any] = {
    "BINANCE": BinanceREST,
    "BINGX":   BingXREST,
}

class Executor:
    def __init__(self, name: Literal["BINANCE","BINGX"]="BINANCE") -> None:
        self.rest = _EXCH[name]()               # type: ignore

    async def new_order(self, side: str, qty: float, price: float | None = None) -> Mapping[str, Any]:
        return await self.rest.new_order(side, qty, price)

    async def close(self): await self.rest.close()
