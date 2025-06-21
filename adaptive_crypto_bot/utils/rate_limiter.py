"""Асинхронный токен-бакет (очень лёгкий)."""

import asyncio
from contextlib import asynccontextmanager
from time import monotonic

class AsyncRateLimiter:
    def __init__(self, rate: int, per: float = 1.0) -> None:
        self._rate = rate
        self._per  = per
        self._tokens = rate
        self._last   = monotonic()
        self._lock   = asyncio.Lock()

    async def _take(self) -> None:
        async with self._lock:
            now = monotonic()
            delta = now - self._last
            # докапываем токены
            self._tokens = min(self._rate, self._tokens + delta * (self._rate / self._per))
            self._last = now
            # ждём, пока появится хотя бы 1 токен
            while self._tokens < 1:
                await asyncio.sleep(self._per / self._rate)
                now = monotonic()
                delta = now - self._last
                self._tokens = min(self._rate, self._tokens + delta * (self._rate / self._per))
                self._last = now
            self._tokens -= 1

    async def __aenter__(self):
        await self._take()
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

# alias for `async with limiter:`
@asynccontextmanager
async def limit(rate: int, per: float = 1.0):
    rl = AsyncRateLimiter(rate, per)
    await rl._take()
    try:
        yield
    finally:
        pass
