"""Мини-клиент Binance SPOT (REST + WebSocket trade-stream).

Документация:
  • https://binance-docs.github.io/apidocs/spot/en/
  • stream: wss://stream.binance.com:9443/ws/<symbolLower>@trade
限制: 1200 req/min ⇒ 20 req/sec – держим лимит.
"""
from __future__ import annotations
import aiohttp, asyncio, hmac, hashlib, time, logging, json, urllib.parse
from typing import Dict, Any, AsyncGenerator, Optional

from adaptive_crypto_bot.core.models import Tick, Side
from adaptive_crypto_bot.utils.rate_limiter import AsyncRateLimiter

_LOG = logging.getLogger("binance")

BASE_REST = "https://api.binance.com"
WS_TRADE  = "wss://stream.binance.com:9443/ws"

class BinanceClient:
    def __init__(self, api_key: str, secret: str, symbol: str = "BTCUSDT") -> None:
        self.key  = api_key
        self.sec  = secret.encode()
        self.sym  = symbol.upper()
        self.sess = aiohttp.ClientSession()
        # 20 req/s
        self.limiter = AsyncRateLimiter(20, 1.0)

    # ── подпись qs ────────────────────────────────────────────────────────────
    def _sign(self, qs: str) -> str:
        return hmac.new(self.sec, qs.encode(), hashlib.sha256).hexdigest()

    async def _req(
        self, method: str, path: str, params: Optional[Dict[str, Any]] = None, auth=False
    ) -> Any:
        params = params or {}
        headers = {}
        if auth:
            params["timestamp"] = int(time.time() * 1000)
            qs_no_sig = urllib.parse.urlencode(params, True)
            params["signature"] = self._sign(qs_no_sig)
            headers["X-MBX-APIKEY"] = self.key
        url = f"{BASE_REST}{path}"
        async with self.limiter:
            async with self.sess.request(method, url, params=params, headers=headers) as r:
                r.raise_for_status()
                return await r.json()

    # ── PUBLIC ────────────────────────────────────────────────────────────────
    async def ping(self) -> bool:
        try:
            await self._req("GET", "/api/v3/ping")
            return True
        except Exception as e:
            _LOG.warning("Ping failed: %s", e)
            return False

    # ── PRIVATE trade ops ─────────────────────────────────────────────────────-
    async def create_order(
        self, side: Side, qty: float, price: float
    ) -> Dict[str, Any]:
        data = dict(
            symbol=self.sym,
            side=side.value,
            type="LIMIT",
            quantity=f"{qty:.6f}",
            price=f"{price:.2f}",
            timeInForce="GTC",
        )
        return await self._req("POST", "/api/v3/order", data, auth=True)

    async def cancel(self, order_id: str) -> Any:
        return await self._req(
            "DELETE", "/api/v3/order", {"symbol": self.sym, "orderId": order_id}, auth=True
        )

    # ── WS trade-stream ───────────────────────────────────────────────────────
    async def ticker_stream(self) -> AsyncGenerator[Tick, None]:
        uri = f"{WS_TRADE}/{self.sym.lower()}@trade"
        async with aiohttp.ClientSession() as sess:
            async with sess.ws_connect(uri, heartbeat=60) as ws:
                async for msg in ws:
                    if msg.type != aiohttp.WSMsgType.TEXT:
                        continue
                    d = json.loads(msg.data)
                    yield Tick(
                        ts   = int(d["T"]),
                        price= float(d["p"]),
                        qty  = float(d["q"]),
                        side = Side.SELL if d["m"] else Side.BUY,
                        src  = "BIN",
                    )

    async def close(self):
        await self.sess.close()
