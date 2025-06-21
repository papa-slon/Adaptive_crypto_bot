"""Минимально-достаточный клиент Binance Spot."""
from __future__ import annotations
import hmac, hashlib, time, aiohttp, json, logging, urllib.parse, asyncio
from adaptive_crypto_bot.config import get_settings
from adaptive_crypto_bot.utils.logging import setup

log = setup()
S   = get_settings()

_BASE_URL = "https://api.binance.com"
_WS_URL   = f"wss://stream.binance.com:9443/ws/{S.SYMBOL.lower()}@trade"


class BinanceREST:
    """REST-часть Binance API (только то, что нужно боту)."""
    def __init__(self) -> None:
        self._s = aiohttp.ClientSession()

    async def _req(self, method: str, path: str, auth: bool = False, **params) -> dict:
        ts = int(time.time() * 1000)
        params["timestamp"] = ts
        q = urllib.parse.urlencode({k: v for k, v in params.items() if v is not None}, True)
        headers: dict[str, str] = {}
        if auth:
            sig = hmac.new(S.BINANCE_SECRET.encode(), q.encode(), hashlib.sha256).hexdigest()
            q = f"{q}&signature={sig}"
            headers["X-MBX-APIKEY"] = S.BINANCE_API_KEY
        url = f"{_BASE_URL}{path}?{q}"
        async with self._s.request(method, url, headers=headers) as r:
            data = await r.json()
            if r.status != 200:
                raise RuntimeError(f"Binance error {data}")
            return data

    # ───── public helpers ─────
    async def ping(self) -> dict:                     # healthcheck
        return await self._req("GET", "/api/v3/ping")

    async def new_order(self, side: str, qty: float, price: float | None = None):
        typ = "LIMIT" if price else "MARKET"
        return await self._req(
            "POST", "/api/v3/order", True,
            symbol=S.SYMBOL, side=side.upper(), type=typ,
            quantity=qty, price=price, timeInForce="GTC" if price else None
        )

    async def close(self): await self._s.close()


async def trade_socket():
    """Асинхронный генератор тиков Binance."""
    async with aiohttp.ClientSession() as s, s.ws_connect(_WS_URL, heartbeat=60) as ws:
        async for msg in ws:
            if msg.type is aiohttp.WSMsgType.TEXT:
                d = json.loads(msg.data)
                yield {
                    "ts": d["T"], "price": float(d["p"]), "qty": float(d["q"]),
                    "side": "sell" if d["m"] else "buy", "src": "BIN"
                }
            elif msg.type is aiohttp.WSMsgType.ERROR:
                log.error("WS error: %s", msg)
                break


# мини-самотест
if __name__ == "__main__":                            # pragma: no cover
    async def _test():
        async for t in trade_socket():
            print(t)
    asyncio.run(_test())
