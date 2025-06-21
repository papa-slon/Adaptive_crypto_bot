"""Мини-SDK для BingX (REST + WebSocket).  Покрывает:
   • тик-стрим (WebSocket)
   • размещение / отмену ордеров (REST)
   • получение баланса / позиций

Документация: https://bingx-api.github.io/docs/
Шифрование сигнатуры: HMAC-SHA256 на (query_string + ''&timestamp=…'')
"""

from __future__ import annotations
import hmac, hashlib, time, aiohttp, asyncio, json, logging, urllib.parse
from typing import Dict, Any, AsyncGenerator, Optional

from adaptive_crypto_bot.core.models import Tick, Side
from adaptive_crypto_bot.utils.rate_limiter import AsyncRateLimiter

_LOG = logging.getLogger("bingx")

BASE_REST = "https://open-api.bingx.com/api/v4"
WS_TRADE  = "wss://open-api.bingx.com/market"

class BingXClient:
    def __init__(self, api_key: str, secret: str, symbol: str = "BTC-USDT") -> None:
        self.api_key = api_key
        self.secret  = secret.encode()
        self.symbol  = symbol
        self.session = aiohttp.ClientSession()
        # 30 req / 3 s  ⇒ 10 req/s
        self.limiter = AsyncRateLimiter(rate=10, per=1.0)

    # ── подпись ────────────────────────────────────────────────────────────────
    def _sign(self, qs: str) -> str:
        return hmac.new(self.secret, qs.encode(), hashlib.sha256).hexdigest()

    # ── унифицированный REST ───────────────────────────────────────────────────
    async def _request(
        self,
        method: str,
        path: str,
        params: Optional[Dict[str, Any]] = None,
        auth: bool = False,
    ) -> Any:
        params = params or {}
        if auth:
            params["timestamp"] = int(time.time() * 1000)
            qs_no_sig = urllib.parse.urlencode(sorted(params.items()))
            params["signature"] = self._sign(qs_no_sig)
            headers = {"X-BX-APIKEY": self.api_key}
        else:
            headers = {}

        url = f"{BASE_REST}{path}"
        async with self.limiter:
            async with self.session.request(method, url, params=params, headers=headers) as r:
                r.raise_for_status()
                return await r.json()

    # ── PUBLIC endpoints ───────────────────────────────────────────────────────
    async def ping(self) -> bool:
        try:
            await self._request("GET", "/ping")
            return True
        except Exception as e:
            _LOG.warning("Ping error: %s", e)
            return False

    # ── PRIVATE endpoints (trading) ────────────────────────────────────────────
    async def create_order(
        self, side: Side, qty: float, price: float
    ) -> Dict[str, Any]:
        data = {
            "symbol": self.symbol,
            "price": price,
            "quantity": qty,
            "side": side.value,
            "type": "LIMIT",
            "timeInForce": "GTC",
        }
        return await self._request("POST", "/trade/order", data, auth=True)

    async def cancel(self, order_id: str) -> Any:
        return await self._request(
            "DELETE", "/trade/order", {"orderId": order_id, "symbol": self.symbol}, auth=True
        )

    # ── WS тик-стрим ───────────────────────────────────────────────────────────
    async def ticker_stream(self) -> AsyncGenerator[Tick, None]:
        uri = f"{WS_TRADE}?symbol={self.symbol.lower()}@trade"
        async with aiohttp.ClientSession() as sess:
            async with sess.ws_connect(uri, heartbeat=30) as ws:
                async for msg in ws:
                    if msg.type != aiohttp.WSMsgType.TEXT:
                        continue
                    data = json.loads(msg.data)
                    tick = Tick(
                        ts   = int(data["T"]),
                        price= float(data["p"]),
                        qty  = float(data["q"]),
                        side = Side.BUY if not data["m"] else Side.SELL,
                        src  = "BGX",
                    )
                    yield tick

    # ── graceful shutdown ──────────────────────────────────────────────────────
    async def close(self) -> None:
        await self.session.close()
