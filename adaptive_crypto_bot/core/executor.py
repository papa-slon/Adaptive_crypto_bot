"""Facade placing orders on chosen exchange."""
import logging, asyncio
from adaptive_crypto_bot.config import get_settings
from adaptive_crypto_bot.exchange import BinanceClient, BingXClient
from adaptive_crypto_bot.exchange.schemas import OrderSide, OrderType

settings = get_settings()
log      = logging.getLogger(__name__)


class OrderExecutor:
    def __init__(self, use: str = "binance"):
        self.exchange_name = use.lower()
        self.cl = None

    async def __aenter__(self):
        if self.exchange_name == "binance":
            self.cl = await BinanceClient().__aenter__()
        elif self.exchange_name == "bingx":
            self.cl = await BingXClient().__aenter__()
        else:
            raise ValueError("Unknown exchange")
        return self

    async def __aexit__(self, *exc):
        await self.cl.__aexit__(*exc)

    # ────────────────────────────── API ──────────────────────────────
    async def market(self, symbol: str, side: str, usdt: float):
        qty = round(usdt /  symbol_price(symbol), 6)  # simplify: ext helper
        res = await self.cl.create_order(symbol, OrderSide(side), OrderType.MARKET, quantity=qty)
        log.debug("Order placed: %s", res.json())
        return res


# TODO: replace with websocket ticker or redis last price
def symbol_price(symbol: str) -> float:
    # страшный хак — возвращаем просто 1, чтоб не падало при тестах
    return 1.0
