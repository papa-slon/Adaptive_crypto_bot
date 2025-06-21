"""
DCA-стратегия (Dollar-Cost Averaging) для адаптивного бота.

▪ Стратегия открывает «базовый» ордер фиксированной величины.
▪ Если цена идёт против позиции на N × step %, выставляется
  «усредняющий» лимит-ордер (safety-order) увеличенного объёма.
▪ TP (take-profit) рассчитывается как средневзвешенная цена × (1 + tp%)
  и выставляется ОДИН раз на весь усреднённый объём.
▪ Размеры, шаги и лимиты берутся из `Settings`.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import List, Optional, Iterable

from adaptive_crypto_bot.config import get_settings
from adaptive_crypto_bot.models import Side, Order, Position    # готовые схемы
from adaptive_crypto_bot.services.order_manager import Executor
from adaptive_crypto_bot.utils.logging_setup import setup

S = get_settings()
log = setup(__name__)


@dataclass(slots=True)
class Slot:
    """Одна DCA-цепочка."""
    entry_price: float
    total_qty: float
    safety_used: int = 0
    tp_order_id: Optional[str] = None

    def avg_price(self) -> float:
        return self.entry_price

    def as_position(self, side: Side) -> Position:
        return Position(
            side=side,
            qty=self.total_qty,
            price=self.entry_price,     # средняя (пересчитается извне при safety)
        )


class DCAStrategy:
    """
    Один экземпляр управляет ВСЕМИ слотами (макс = `S.MAX_SLOTS`).

    Публичные методы вызываются из `worker.py`.
    """

    def __init__(self, executor: Executor) -> None:
        self.ex: Executor = executor
        self.side: Side = Side.BUY       # пока работаем только long; позже — оба
        self.slots: List[Slot] = []

        # параметры стратегии – возможно разные для long / short
        self.base_usd = S.BASE_ORDER_USDT
        self.safety_usd = S.SAFETY_ORDER_USDT
        self.safety_step_pct = 1.2       # шаг усреднения (проценты)
        self.tp_pct = 0.35               # целевая прибыль

    # ─────────────────────────── helpers ────────────────────────────

    async def _place_tp(self, slot: Slot) -> None:
        """Выставить / перевыставить take-profit-ордер."""
        tp_price = round(slot.avg_price() * (1 + self.tp_pct / 100), 2)
        if slot.tp_order_id:
            await self.ex.cancel(slot.tp_order_id)
        order = await self.ex.limit(
            side=Side.SELL, qty=slot.total_qty, price=tp_price
        )
        slot.tp_order_id = order.order_id
        log.debug("TP placed %s for slot %s", order, slot)

    async def _maybe_place_safety(self, slot: Slot, price: float) -> None:
        """
        Если цена «ушла» вниз на N × step%, ставим очередную safety-лимитку.

        safety-лимитка ставится немного ниже рыночной цены,
        чтобы гарантированно забрать исполнение.
        """
        target_drop = (slot.safety_used + 1) * self.safety_step_pct / 100
        if price <= slot.entry_price * (1 - target_drop):
            qty = round(self.safety_usd / price, 6)
            limit_price = round(price * 0.995, 2)
            order = await self.ex.limit(side=Side.BUY, qty=qty, price=limit_price)
            slot.total_qty += qty
            slot.entry_price = (slot.entry_price * slot.total_qty + limit_price * qty) / (
                slot.total_qty + qty
            )
            slot.safety_used += 1
            log.info("Safety-order filled %s", order)
            await self._place_tp(slot)

    # ─────────────────────────── public API ─────────────────────────

    async def on_tick(self, price: float) -> None:
        """
        Реакция на каждый тик.

        1. Если нет активных слотов — открываем новый базовый ордер.
        2. По каждому открытому слоту проверяем safety-условие.
        """
        # 1. новый слот
        if len(self.slots) < S.MAX_SLOTS:
            await self._open_base(price)

        # 2. проверка усреднений
        await asyncio.gather(*[self._maybe_place_safety(s, price) for s in self.slots])

    # ─────────────────────────── primitives ─────────────────────────

    async def _open_base(self, price: float) -> None:
        qty = round(self.base_usd / price, 6)
        order = await self.ex.market(side=Side.BUY, qty=qty)
        slot = Slot(entry_price=order.price, total_qty=order.qty)
        self.slots.append(slot)
        log.info("Base order filled %s", order)
        await self._place_tp(slot)

    # ─────────────────────────── recovery / sync ────────────────────

    async def sync_positions(self) -> None:
        """
        Синхронизировать слоты из фактических позиций на бирже.

        (на случай рестарта контейнера).
        """
        positions = await self.ex.positions()
        # … реализация зависит от `Executor`; пропускаем для brevity
        if positions:
            log.warning("SYNC NOT IMPLEMENTED, found %s", positions)

