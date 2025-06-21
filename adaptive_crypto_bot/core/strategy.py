"""Стратегия: базовый ордер + N «safety-order» по сетке.

Алгоритм:
1. При каждом новом тике обновляем last_price.
2. Если нет активных слотов → ставим base-order (market/limit).
3. Если есть открытые позиции -- ставим safety-orders ступенями ±X %.
4. Контролируем MAX_SLOTS – не открываем новых, пока есть старые.
"""

from __future__ import annotations
import asyncio, logging
from dataclasses import dataclass, field
from typing import List

from adaptive_crypto_bot.config import get_settings
from adaptive_crypto_bot.core.models import Tick, Side, Order

cfg = get_settings()
_LOG = logging.getLogger("strategy")

# ─────────── dataclass для слота - хранит context позиции ───────────
@dataclass
class Slot:
    base_order: Order
    safety_orders: List[Order] = field(default_factory=list)

class DcaStrategy:
    def __init__(self) -> None:
        self.slots: List[Slot] = []
        self.last_price: float = 0.0

    # ── интерфейс для main-loop ───────────────────────────────────────────────
    async def on_tick(self, tick: Tick, executor) -> None:
        self.last_price = tick.price

        # 1. закрываем заполненные слоты
        self.slots = [s for s in self.slots if s.base_order.status != "FILLED"]

        # 2. можно ли создать новый?
        if len(self.slots) < cfg.MAX_SLOTS:
            await self._maybe_open_slot(executor)

        # 3. апдейт safety-orders
        await self._manage_safety_orders(executor)

    # ─────────── helpers ──────────────────────────────────────────────────────
    async def _maybe_open_slot(self, executor):
        qty  = cfg.BASE_ORDER_USDT / self.last_price
        order = await executor.place_order(Side.BUY, qty, self.last_price * 0.999)
        slot  = Slot(base_order=order)
        self.slots.append(slot)
        _LOG.info("New slot opened @$%.2f", order.price)

    async def _manage_safety_orders(self, executor):
        for slot in self.slots:
            # если base-order заполнен & нет safety-ов → ставим первый
            if slot.base_order.status == "FILLED" and not slot.safety_orders:
                await self._place_safety(slot, executor)
            # если есть исполненный safety → ставим следующий
            if slot.safety_orders and slot.safety_orders[-1].status == "FILLED":
                await self._place_safety(slot, executor)

    async def _place_safety(self, slot: Slot, executor):
        step_pct = 0.5  # каждая ступень 0.5 %
        target_px = slot.base_order.price * (1 - step_pct * (1 + len(slot.safety_orders)))
        qty = cfg.SAFETY_ORDER_USDT / target_px
        order = await executor.place_order(Side.BUY, qty, target_px)
        slot.safety_orders.append(order)
        _LOG.info("Safety order #%d @$%.2f", len(slot.safety_orders), order.price)
