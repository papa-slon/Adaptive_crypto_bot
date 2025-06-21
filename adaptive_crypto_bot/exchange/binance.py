"""Very small async Binance REST client (spot)."""
from __future__ import annotations
import hmac, hashlib, time, logging, os
from urllib.parse import urlencode

import httpx
from adaptive_crypto_bot.exchange.schemas import OrderSide, OrderType

log = logging.getLogger(__name__)
BASE = "https://api.binance.com"


class BinanceClient:
    def __init__(self):
        self.key = os.environ["BINANCE_API_KEY"]
        self.sec = os.environ["BINANCE_SECRET"]
        self.cl: httpx.AsyncClient | None = None

    # ─────────────────────── context mgmt ───────────────────────
    async def __aenter__(self):
        self.cl = httpx.AsyncClient(base_url=BASE, timeout=10.0)
        return self

    async def __aexit__(self, *exc):
        await self.cl.aclose()

    # ───────────────────────── helpers ──────────────────────────
    def _sign(self, params: dict[str, str]) -> str:
        qs = urlencode(params)
        sig = hmac.new(self.sec.encode(), qs.encode(), hashlib.sha256).hexdigest()
        return f"{qs}&signature={sig}"

    async def _req(self, meth: str, path: str, *, auth: bool = False, **params):
        p = params.copy()
        if auth:
            p["timestamp"] = int(time.time() * 1000)
            query = self._sign(p)
            hdrs  = {"X-MBX-APIKEY": self.key}
        else:
            query = urlencode(p)
            hdrs  = None
        url = f"{path}?{query}" if query else path
        r = await self.cl.request(meth, url, headers=hdrs)
        r.raise_for_status()
        return r.json()

    # ─────────────────────── public API ────────────────────────
    async def create_order(
        self,
        symbol: str,
        side:   OrderSide,
        typ:    OrderType,
        quantity: float,
    ):
        return await self._req(
            "POST",
            "/api/v3/order",
            auth=True,
            symbol=symbol,
            side=side.value,
            type=typ.value,
            quantity=str(quantity),
        )
