"""Минимальный REST-клиент Binance (Spot).  Только то, что нужно боту."""
from __future__ import annotations
import os, time, hmac, hashlib, urllib.parse, aiohttp, logging, asyncio
from typing import Any, Dict

from adaptive_crypto_bot.utils.logging import setup
from adaptive_crypto_bot.config        import get_settings

log = setup("BinanceREST")
S   = get_settings()

BASE  = "https://api.binance.com"

class BinanceREST:
    def __init__(self) -> None:
        self._s: aiohttp.ClientSession | None = None

    # ────────────────────────── helpers ──────────────────────────
    async def _session(self) -> aiohttp.ClientSession:
        if not self._s:
            self._s = aiohttp.ClientSession()
        return self._s

    def _sign(self, q: str) -> str:
        return hmac.new(S.BINANCE_SECRET.encode(), q.encode(), hashlib.sha256).hexdigest()

    async def _req(
        self,
        method: str,
        path: str,
        signed: bool = False,
        **params: Any,
    ) -> Dict[str, Any]:
        if signed:
            params["timestamp"] = int(time.time() * 1000)
        qs  = urllib.parse.urlencode(params, True)
        if signed:
            qs += f"&signature={self._sign(qs)}"
        url = f"{BASE}{path}?{qs}" if qs else f"{BASE}{path}"
        hdr = {"X-MBX-APIKEY": S.BINANCE_API_KEY} if signed else {}

        s = await self._session()
        async with s.request(method, url, headers=hdr) as r:
            data = await r.json()
            if r.status != 200:  # Binance в ошибке держит {"code": -… , "msg": "..."}
                raise RuntimeError(f"{r.status} {data}")
            return data

    # ────────────────────────── public → info ──────────────────────────
    async def ping(self) -> bool:
        await self._req("GET", "/api/v3/ping")
        return True

    # ────────────────────────── signed → trading ───────────────────────
    async def new_order(
        self,
        side: str,
        quantity: float,
        price: float | None = None,
        reduce_only: bool   = False,
    ) -> Dict[str, Any]:
        typ = "LIMIT" if price else "MARKET"
        params = dict(
            symbol   = S.SYMBOL,
            side     = side.upper(),
            type     = typ,
            quantity = quantity,
            recvWindow=5000,
        )
        if price:
            params.update(price=price, timeInForce="GTC")
        if reduce_only:
            params["sideEffectType"] = "AUTO_REPAY"

        return await self._req("POST", "/api/v3/order", signed=True, **params)

    async def close(self):
        if self._s and not self._s.closed:
            await self._s.close()
