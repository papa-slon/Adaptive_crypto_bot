"""Very simple Dollar-Cost-Averaging strategy implementation.

Алгоритм:
1. Получаем тики из Redis-стрима.
2. На каждом тике проверяем:
   • нет позиции — ставим MARKET BUY base USDT
   • есть позиция long:
        если цена упала > X% от средней  ⇒ ставим MARKET BUY safety
        если цена выросла > TP          ⇒ ставим MARKET SELL всё
   • всё симметрично для short (не реализовано для краткости)
Параметры берём из Settings.
"""
from __future__ import annotations
import asyncio, logging, math
from collections import deque
from typing import Deque, Callable, Awaitable

from redis.asyncio import Redis
from adaptive_crypto_bot.config import get_settings
from adaptive_crypto_bot.core.models import Tick, Position

settings = get_settings()
log      = logging.getLogger(__name__)

SAFETY_TRIGGER = 1.5 / 100        # 1.5 %
TAKE_PROFIT    = 2.0 / 100        # 2 %


class DcaStrategy:
    def __init__(
        self,
        redis: Redis,
        exec_order: Callable[[str, str, float], Awaitable[None]],  # exec(symbol, side, usdt)
    ):
        self.r            = redis
        self.exec_order   = exec_order
        self.position: Position | None = None
        self.recent: Deque[float] = deque(maxlen=20)

    # ───────────────────────── helpers ──────────────────────────
    def _avg(self) -> float:
        return sum(self.recent) / len(self.recent)

    # ───────────────────── main event-loop ──────────────────────
    async def run(self):
        log.info("DCA-strategy started")
        last_id = "0-0"
        while True:
            result = await self.r.xread({settings.REDIS_STREAM: last_id}, block=5000, count=100)
            if not result:
                continue
            _, entries = result[0]
            for eid, data in entries:
                last_id = eid
                tick = Tick.model_validate(data)
                self.recent.append(tick.price)
                await self._on_tick(tick)

    async def _on_tick(self, t: Tick):
        if not self.position:
            # no active position, open new slot
            await self.exec_order(settings.SYMBOL, "BUY", settings.BASE_ORDER_USDT)
            self.position = Position(symbol=settings.SYMBOL, entry=t.price, qty=settings.BASE_ORDER_USDT / t.price, side="long")
            log.info("Opened new position @ %.2f", t.price)
            return

        # update unrealised pnl
        self.position.unreal_pnl = (t.price - self.position.entry) / self.position.entry

        # safety order?
        drawdown = (self.position.entry - t.price) / self.position.entry
        if drawdown > SAFETY_TRIGGER and self.position.qty < settings.MAX_SLOTS * settings.SAFETY_ORDER_USDT / t.price:
            await self.exec_order(settings.SYMBOL, "BUY", settings.SAFETY_ORDER_USDT)
            new_qty   = self.position.qty + settings.SAFETY_ORDER_USDT / t.price
            new_entry = (self.position.entry * self.position.qty + t.price * (settings.SAFETY_ORDER_USDT / t.price)) / new_qty
            self.position.qty, self.position.entry = new_qty, new_entry
            log.info("Safety order executed, new avg %.2f", new_entry)
            return

        # take-profit?
        if self.position.unreal_pnl >= TAKE_PROFIT:
            await self.exec_order(settings.SYMBOL, "SELL", self.position.qty * t.price)
            log.info("TP hit (%.2f%%), closing position", self.position.unreal_pnl * 100)
            self.position = None
