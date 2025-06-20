"""
adaptive_crypto_bot/utils/rate_limiter.py

Асинхронный «token-bucket» для контроля частоты HTTP/WS-запросов.

▪ rps — «requests-per-second» (ёмкость в токенах).
▪ `acquire()` блокирует корутину, пока не появится свободный токен.
▪ Потокобезопасен для множества concurrent `await`'ов.
"""

from __future__ import annotations

import asyncio
import time


class RateLimiter:
    """Token-bucket с support `async with`."""

    MIN_SLEEP = 0.05  # 50 мс, чтобы не жечь CPU при плотном цикле

    def __init__(self, rps: int) -> None:
        if rps <= 0:
            raise ValueError("rps must be > 0")
        self._capacity: float = float(rps)
        self._tokens:   float = float(rps)
        self._last_refill: float = time.monotonic()
        self._lock = asyncio.Lock()

    # ──────────────────────────────── API ────────────────────────────────
    async def acquire(self) -> None:
        """Блокируется, пока в «ведре» не окажется ≥ 1 токена."""
        async with self._lock:
            while True:
                now = time.monotonic()
                delta = now - self._last_refill
                self._last_refill = now

                # «доливаем» токены со скоростью rps/сек, но не переливаем
                self._tokens = min(self._capacity,
                                   self._tokens + delta * self._capacity)

                if self._tokens >= 1.0:
                    self._tokens -= 1.0
                    return

                await asyncio.sleep(self.MIN_SLEEP)

    # — enable `async with limiter:` —
    async def __aenter__(self):  # noqa: D401
        await self.acquire()
        return self

    async def __aexit__(self, *_exc):
        # nothing to cleanup
        return False
