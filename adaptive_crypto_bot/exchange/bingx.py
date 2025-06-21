"""Async BingX REST+WS client (минимум, который нужен боту)."""
from __future__ import annotations

import hmac, hashlib, json, logging, time, aiohttp, websockets
from typing import Any, Dict

from adaptive_crypto_bot.config import get_settings
from .schemas import OrderSide, OrderType, OrderResponse

settings = get_settings()
log      = logging.getLogger(__name__)

REST = "https://open-api.bingx.com/openApi"
WS   = "wss://open-api.bingx.com/market"


class BingXClient:
    def __init__(
        self,
        api_key: str = settings.BINGX_API_KEY,
        secret:  str = settings.BINGX_SECRET,
        session: aiohttp.ClientSession | None = None,
    ):
        self.api_key = api_key
        self._secret = secret
        self._s      = session or aiohttp.ClientSession()
        self._closed = False

    # ───────────────────────── helpers ──────────────────────────
    def _ts(self) -> int:
        return int(time.time() * 1000)

    def _sign(self, query: str) -> str:
        return hmac.new(self._secret.encode(), query.encode(), hashlib.sha256).hexdigest()

    async def _req(self, method: str, path: str, params: Dict[str, Any] | None = None):
        params = params or {}
        params["timestamp"] = self._ts()
        query  = "&".join(f"{k}={v}" for k, v in sorted(params.items()))
        sig    = self._sign(query)
        url    = f"{REST}{path}?{query}&signature={sig}"
        headers = {"X-BX-APIKEY": self.api_key}
        async with self._s.request(method, url, headers=headers) as r:
            data = await r.json()
            if r.status != 200 or data.get("code") not in (0, "0"):
                raise RuntimeError(f"BingX error {r.status}: {data}")
            return data["data"] if "data" in data else data

    # ───────────────────────── REST ─────────────────────────────
    async def create_order(
        self, symbol: str, side: OrderSide, type_: OrderType, quantity: float, price: float | None = None
    ) -> OrderResponse:
        body = {
            "symbol": symbol,
            "side": side.value.lower(),
            "type": type_.value.lower(),
            "price": price or 0,
            "quantity": quantity,
        }
        data = await self._req("POST", "/v1/order/place", body)
        return OrderResponse.model_validate(data)

    async def cancel_order(self, symbol: str, order_id: str) -> bool:
        await self._req("DELETE", "/v1/order/cancel", {"symbol": symbol, "orderId": order_id})
        return True

    # ──────────────────────── WebSocket ─────────────────────────
    async def trades(self, symbol: str):
        uri = f"{WS}?symbol={symbol}"
        async with websockets.connect(uri, ping_interval=None) as ws:
            async for msg in ws:
                yield json.loads(msg)

    # ───────────────────────── cleanup ──────────────────────────
    async def close(self):
        if not self._closed:
            self._closed = True
            await self._s.close()

    async def __aenter__(self): return self
    async def __aexit__(self, *exc): await self.close()
