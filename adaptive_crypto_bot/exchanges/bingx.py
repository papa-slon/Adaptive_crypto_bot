"""Мини-REST/WS клиент BingX (Spot & Futures).  Достаточно для базовых ордеров."""
from __future__ import annotations
import hmac, hashlib, time, aiohttp, asyncio, logging, urllib.parse

from adaptive_crypto_bot.config        import get_settings
from adaptive_crypto_bot.utils.logging import setup

S   = get_settings()
log = setup("bingx")

_BASE_URL = "https://open-api.bingx.com"
_WS_URL   = f"wss://open-api.bingx.com/market"

class BingxREST:
    def __init__(self) -> None:
        self._s = aiohttp.ClientSession()

    # ───────────────────────────── private helpers
    def _sign(self, query: str) -> str:
        return hmac.new(S.BINGX_SECRET.encode(), query.encode(), hashlib.sha256).hexdigest()

    async def _req(self, method: str, path: str, auth: bool = False, **params) -> dict:
        ts = int(time.time() * 1000)
        params["timestamp"] = ts
        q = urllib.parse.urlencode(params, True)
        headers = {}
        if auth:
            q += f"&signature={self._sign(q)}"
            headers["X-BX-APIKEY"] = S.BINGX_API_KEY
        url = _BASE_URL + path + "?" + q
        async with self._s.request(method, url, headers=headers) as r:
            data = await r.json()
            if r.status != 200 or str(data.get("code")) not in ("0", "200"):
                raise RuntimeError(f"BingX error {data}")
            return data["data"] if "data" in data else data

    # ───────────────────────────── public REST
    async def new_order(self, side: str, qty: float, price: float | None = None):
        typ = "LIMIT" if price else "MARKET"
        return await self._req(
            "POST", "/openApi/spot/v1/trade/order",
            auth=True, symbol=S.SYMBOL, side=side.upper(),
            type=typ, quantity=qty, price=price or ""
        )

    async def cancel_all(self):
        return await self._req(
            "DELETE", "/openApi/spot/v1/trade/openOrders", auth=True, symbol=S.SYMBOL
        )

    async def get_depth(self, limit: int = 5):
        return await self._req(
            "GET", "/openApi/spot/v1/market/depth", symbol=S.SYMBOL, limit=limit
        )

    # ───────────────────────────── graceful close
    async def close(self):
        await self._s.close()

# ───────────────────────────── simple WS stream (trades)
async def trades():
    """Асинхронный генератор тиков."""
    async with aiohttp.ClientSession() as s, s.ws_connect(f"{_WS_URL}?symbol={S.SYMBOL}") as ws:
        async for msg in ws:
            if msg.type == aiohttp.WSMsgType.TEXT:
                yield msg.json()
