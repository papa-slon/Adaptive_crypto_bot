# adaptive_crypto_bot/exchanges/binance_client.py
"""
Публичный клиент Binance (Futures) для:
• REST-эндпоинта klines
• WebSocket-потока kline_1m             → on_kline() вызывается, когда свеча ЗАКРЫТА
Авторизация не нужна.
"""
from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, Callable, Dict, List, Sequence

import aiohttp

from adaptive_crypto_bot.config import get_settings

log = logging.getLogger(__name__)
settings = get_settings()

_BASE_REST = "https://fapi.binance.com"
_BASE_WS   = "wss://fstream.binance.com:9443/stream"


class BinanceClient:
    """Лёгкий stateful-клиент: одна aiohttp-сессия на весь объект."""

    def __init__(self) -> None:
        self._session: aiohttp.ClientSession | None = None

    # ───────────────────────── REST ─────────────────────────
    async def get_klines(                     # 1-мин бары
        self,
        symbol: str,
        *,
        interval: str = "1m",
        limit: int = 200,
    ) -> Sequence[Any]:
        if self._session is None:
            self._session = aiohttp.ClientSession()
        url = f"{_BASE_REST}/fapi/v1/klines"
        params = {"symbol": symbol, "interval": interval, "limit": limit}
        async with self._session.get(url, params=params, timeout=10) as r:
            r.raise_for_status()
            js = await r.json()
            log.debug("klines %s %s×%s", symbol, interval, len(js))
            return js  # [[openTime, o,h,l,c, …], …]

    # ─────────────────────── WebSocket ──────────────────────
    async def start_kline_ws(
        self,
        symbols: List[str],
        on_kline: Callable[[str, Dict[str, Any]], None],
    ) -> None:
        """
        Подписывается на «закрытые» 1-мин свечи для symbols.
        on_kline(symbol, k) вызывается КАЖДУЮ минуту, когда k["x"] == True.
        """
        if self._session is None:
            self._session = aiohttp.ClientSession()

        streams = "/".join(f"{s.lower()}@kline_1m" for s in symbols)
        url     = f"{_BASE_WS}?streams={streams}"

        while True:  # auto-reconnect без ограничения
            try:
                async with self._session.ws_connect(
                    url,
                    heartbeat=20,
                    max_size=2 ** 20,
                    compress=15,
                ) as ws:
                    log.info("BN WS connected: %s", ",".join(symbols))
                    async for msg in ws:
                        if msg.type is aiohttp.WSMsgType.TEXT:
                            data = json.loads(msg.data)

                            # Binance иногда шлёт {'code':-1121,…}
                            if "code" in data:
                                log.warning("BN WS error %s", data)
                                continue

                            k = data["data"]["k"]
                            if k["x"]:                       # свеча закрылась
                                on_kline(k["s"], k)
                        elif msg.type in (
                            aiohttp.WSMsgType.CLOSED,
                            aiohttp.WSMsgType.ERROR,
                        ):
                            break
            except Exception as e:
                log.error("BN WS exception: %s – reconnect in 5s", e)
                await asyncio.sleep(5)

    # ───────────────────────── util ─────────────────────────
    async def aclose(self) -> None:
        if self._session:
            await self._session.close()

