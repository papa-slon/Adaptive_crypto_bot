"""Async Binance REST+WS client (минимум, который нужен боту)."""
from __future__ import annotations

import asyncio, hmac, hashlib, json, logging, time, aiohttp, websockets
from typing import Any, Dict

from adaptive_crypto_bot.config import get_settings
from .schemas import OrderSide, OrderType, OrderResponse

settings = get_settings()
log      = logging.getLogger(__name__)

REST = "https://api.binance.com"
WS   = "wss://stream.binance.com:9443/ws"


class BinanceClient:
    def __init__(
        self,
        api_key: str = settings.BINANCE_API_KEY,
        secret:  str = settings.BINANCE_SECRET,
        session: aiohttp.ClientSession | None = None,
    ):
        self.api_key = api_key
        self._secret = secret.encode()
        self._s      = session or aiohttp.ClientSession()
        self._closed = False

    # ───────────────────────── helpers ──────────────────────────
    def _ts(self) -> int:
        return int(time.time() * 1000)

    def _sign(self, query: str) -> str:
        return hmac.new(self._secret, query.encode(), hashlib.sha256).hexdigest()

    async def _req(self, method: str, path: str, params: Dict[str, Any] | None = None):
        params = params or {}
        url    = f"{REST}{path}"
        query  = "&".join(f"{k}={v}" for k, v in sorted(params.items()))
        if "timestamp" in params or method != "GET":
            query = f"{query}&timestamp={self._ts()}" if query else f"timestamp={self._ts()}"
            query = f"{query}&signature={self._sign(query)}"
        headers = {"X-MBX-APIKEY": self.api_key}
        async with self._s.request(method, url, params=None if method != "GET" else None, data=query if method != "GET" else None, headers=headers) as r:
            data = await r.json()
            if r.status != 200:
                raise RuntimeError(f"Binance error {r.status}: {data}")
            return data

    # ─────────────────────── public REST ────────────────────────
    async def ping(self) -> bool:
        await self._req("GET", "/api/v3/ping")
        return True

    async def create_order(
        self, symbol: str, side: OrderSide, type_: OrderType, quantity: float, price: float | None = None
    ) -> OrderResponse:
        payload: Dict[str, Any] = {"symbol": symbol, "side": side.value, "type": type_.value, "quantity": quantity}
        if price is not None:
            payload["price"] = price
        data = await self._req("POST", "/api/v3/order", payload)
        return OrderResponse.model_validate(data)

    async def cancel_order(self, symbol: str, order_id: int) -> bool:
        await self._req("DELETE", "/api/v3/order", {"symbol": symbol, "orderId": order_id})
        return True

    # ───────────────────────── WebSocket ────────────────────────
    async def trades(self, symbol: str):
        """Yield raw @trade messages."""
        uri = f"{WS}/{symbol.lower()}@trade"
        async with websockets.connect(uri, ping_interval=20) as ws:
            async for msg in ws:
                yield json.loads(msg)

    # ───────────────────────── cleanup ──────────────────────────
    async def close(self):
        if not self._closed:
            self._closed = True
            await self._s.close()

    # context-manager-style
    async def __aenter__(self): return self
    async def __aexit__(self, *exc): await self.close()
