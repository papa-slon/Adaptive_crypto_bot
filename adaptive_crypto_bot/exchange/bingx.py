"""Very small async BingX client (swap)."""
from __future__ import annotations
import hmac, hashlib, time, logging, os
from urllib.parse import urlencode

import httpx
from adaptive_crypto_bot.exchange.schemas import OrderSide, OrderType

log  = logging.getLogger(__name__)
BASE = "https://open-api.bingx.com"

class BingXClient:
    def __init__(self):
        self.key = os.environ["BINGX_API_KEY"]
        self.sec = os.environ["BINGX_SECRET"]
        self.cl  : httpx.AsyncClient | None = None

    async def __aenter__(self):
        self.cl = httpx.AsyncClient(base_url=BASE, timeout=10.0)
        return self

    async def __aexit__(self, *exc):
        await self.cl.aclose()

    # ───────────────────────── helpers ──────────────────────────
    def _sign(self, params: dict[str, str]) -> dict[str, str]:
        params["timestamp"] = str(int(time.time() * 1000))
        qs = urlencode(sorted(params.items()))
        sig = hmac.new(self.sec.encode(), qs.encode(), hashlib.sha256).hexdigest()
        params["signature"] = sig
        return params

    async def _post(self, path: str, **params):
        p = self._sign(params)
        r = await self.cl.post(path, headers={"X-BX-APIKEY": self.key}, data=p)
        r.raise_for_status()
        return r.json()

    # ───────────────────────── public ───────────────────────────
    async def create_order(
        self, symbol: str, side: OrderSide, typ: OrderType, quantity: float
    ):
        return await self._post(
            "/openApi/spot/v1/trade/order",
            symbol=symbol,
            side=side.value.lower(),     # bingx uses lower-case
            type=typ.value.lower(),
            quantity=str(quantity),
        )
