"""Grid / Safety-order стратегия.

Логика:
* Стартуем с BASE_ORDER_USDT (из Settings) по рынку → открываем «слот».
* Для каждого слота держим цепочку safety-orders,
  – шаг цены (GAP_PCT) и прогрессию суммы (MARTINGALE).
* Если позиция в плюсе на TAKE_PROFIT_PCT → закрываем все ордера слота.
"""
from __future__ import annotations
import asyncio, logging, math
from decimal import Decimal, ROUND_DOWN
from dataclasses import dataclass, field
from adaptive_crypto_bot.config   import get_settings
from adaptive_crypto_bot.utils.logging import setup
from .base import BaseStrategy, Exchange

S   = get_settings()
log = setup()

GAP_PCT           = Decimal("0.7")        # шаг вниз между safety-orders (%)
MARTINGALE        = Decimal("1.3")        # коэффициент наращивания суммы
SAFETY_ORDERS     = 6                     # максимум усреднений на слот
TAKE_PROFIT_PCT   = Decimal("0.8")        # фиксируем +0.8 %

@dataclass
class Order:
    id: str
    qty: Decimal
    price: Decimal

@dataclass
class Slot:
    orders: list[Order]           = field(default_factory=list)
    next_so_idx: int             = 0

class GridStrategy(BaseStrategy):
    def __init__(self, exch: Exchange):
        super().__init__(exch)
        self.slots: list[Slot] = []

    # ───────────────────────────── helpers
    async def _place(self, side: str, usdt: Decimal, ref_price: Decimal) -> Order:
        qty  = (usdt / ref_price).quantize(Decimal("0.000001"), ROUND_DOWN)
        resp = await self.exch.new_order(side, float(qty))       # MARKET
        oid  = resp["orderId"]
        price= Decimal(str(resp["fills"][0]["price"]))
        log.info("%s %.6f @ %.2f", side, qty, price)
        return Order(id=str(oid), qty=qty, price=price)

    # ───────────────────────────── tick handler
    async def on_tick(self, tick: dict[str, float]):             # noqa: D401
        price = Decimal(str(tick["price"]))

        # 1) открываем новые слоты
        if len(self.slots) < S.MAX_SLOTS:
            o = await self._place("BUY", Decimal(str(S.BASE_ORDER_USDT)), price)
            self.slots.append(Slot(orders=[o]))
            return

        # 2) safety-orders + take-profit
        for slot in list(self.slots):                            # copy
            avg_price = sum(o.qty * o.price for o in slot.orders) / sum(o.qty for o in slot.orders)

            # take-profit ?
            tp_lvl = avg_price * (Decimal("1") + TAKE_PROFIT_PCT/Decimal("100"))
            if price >= tp_lvl:
                qty_total = sum(o.qty for o in slot.orders)
                await self._place("SELL", qty_total * price, price)   # простая рыночная продажа
                self.slots.remove(slot)
                continue

            # safety-order ?
            if slot.next_so_idx >= SAFETY_ORDERS: continue
            gap = (slot.next_so_idx + 1) * GAP_PCT / Decimal("100")
            target = avg_price * (Decimal("1") - gap)
            if price <= target:
                usdt = (Decimal(str(S.SAFETY_ORDER_USDT)) *
                        MARTINGALE ** slot.next_so_idx).quantize(Decimal("0.01"))
                o = await self._place("BUY", usdt, price)
                slot.orders.append(o)
                slot.next_so_idx += 1
