"""Разные маленькие вспомогательные функции."""
from __future__ import annotations
import asyncio, backoff, logging
from typing import Callable, Any

log = logging.getLogger("misc")

def retryable(**bo):  # sugar for @backoff.on_exception
    def deco(fn: Callable[..., Any]):
        return backoff.on_exception(
            backoff.expo,
            Exception,
            max_tries = bo.get("tries", 5),
            jitter    = backoff.full_jitter,
        )(fn)
    return deco

def ensure_awaitable(func: Callable[..., Any], *a, **k):
    res = func(*a, **k)
    return res if asyncio.iscoroutine(res) else asyncio.sleep(0, res)
