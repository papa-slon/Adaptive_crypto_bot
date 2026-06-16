"""Venue abstraction for the carry bot + a deterministic PaperVenue.

A `Venue` exposes just what the carry bot needs: a mark price, a spot leg
(buy/sell base), an isolated short-perp leg (open/reduce, margin, funding),
and account read-outs. `PaperVenue` simulates all of it in-process so the bot
logic can be unit-tested and paper-traded with a replayed price/funding feed.

A real Bybit/Binance adapter implements the same methods (REST/WS under the
hood) — the bot code does not change.
"""
from __future__ import annotations

from typing import Protocol


class Venue(Protocol):
    def mark_price(self) -> float: ...
    def buy_spot(self, notional: float) -> None: ...
    def sell_spot_qty(self, qty: float) -> None: ...
    def open_short_perp(self, notional: float, leverage: float) -> None: ...
    def reduce_short_perp_qty(self, qty: float) -> None: ...
    def add_perp_margin(self, amount: float) -> None: ...
    def spot_base_qty(self) -> float: ...
    def perp_short_qty(self) -> float: ...
    def perp_margin_ratio(self) -> float: ...
    def equity(self) -> float: ...


class PaperVenue:
    """In-process paper venue. Drive it with set_price() and apply_funding()."""

    def __init__(self, price: float, cash: float = 1.0, taker_fee: float = 0.0006):
        self._price = float(price)
        self.cash = float(cash)          # free USDT (quote)
        self.taker_fee = float(taker_fee)
        self.base_qty = 0.0              # spot base held (long)
        self.perp_qty = 0.0              # perp position (negative = short)
        self.perp_entry = 0.0
        self.perp_margin = 0.0           # isolated margin posted to the perp leg
        self.funding_collected = 0.0
        self.fees_paid = 0.0

    # ---- feed ----
    def set_price(self, price: float) -> None:
        self._price = float(price)

    def apply_funding(self, rate: float) -> None:
        """Short perp receives `rate * notional` when rate > 0 (longs pay)."""
        pnl = rate * abs(self.perp_qty) * self._price
        self.perp_margin += pnl          # funding settles into the perp margin
        self.funding_collected += pnl

    # ---- Venue API ----
    def mark_price(self) -> float:
        return self._price

    def buy_spot(self, notional: float) -> None:
        fee = notional * self.taker_fee
        self.base_qty += notional / self._price
        self.cash -= notional + fee
        self.fees_paid += fee

    def sell_spot_qty(self, qty: float) -> None:
        notional = qty * self._price
        fee = notional * self.taker_fee
        self.base_qty -= qty
        self.cash += notional - fee
        self.fees_paid += fee

    def open_short_perp(self, notional: float, leverage: float) -> None:
        fee = notional * self.taker_fee
        qty = notional / self._price
        # blend entry if adding to an existing short
        if self.perp_qty == 0:
            self.perp_entry = self._price
        else:
            tot = abs(self.perp_qty) + qty
            self.perp_entry = (self.perp_entry * abs(self.perp_qty) + self._price * qty) / tot
        self.perp_qty -= qty
        self.perp_margin += notional / leverage
        self.cash -= notional / leverage + fee
        self.fees_paid += fee

    def reduce_short_perp_qty(self, qty: float) -> None:
        qty = min(qty, abs(self.perp_qty))
        if qty <= 0:
            return
        notional = qty * self._price
        fee = notional * self.taker_fee
        pnl = (self.perp_entry - self._price) * qty       # short pnl
        frac = qty / abs(self.perp_qty)
        released = self.perp_margin * frac
        self.perp_qty += qty                               # toward zero
        self.perp_margin -= released
        self.cash += released + pnl - fee
        self.fees_paid += fee

    def add_perp_margin(self, amount: float) -> None:
        amount = min(amount, max(self.cash, 0.0))
        self.cash -= amount
        self.perp_margin += amount

    def spot_base_qty(self) -> float:
        return self.base_qty

    def perp_short_qty(self) -> float:
        return abs(self.perp_qty)

    def _perp_upnl(self) -> float:
        # short unrealised pnl: gains when price falls below entry
        return (self.perp_entry - self._price) * abs(self.perp_qty)

    def perp_margin_ratio(self) -> float:
        """Perp-leg equity / notional. Drops toward 0 as the short loses; the
        exchange liquidates near the maintenance ratio."""
        notional = abs(self.perp_qty) * self._price
        if notional <= 0:
            return 1.0
        perp_equity = self.perp_margin + self._perp_upnl()
        return perp_equity / notional

    def equity(self) -> float:
        spot_val = self.base_qty * self._price
        return self.cash + spot_val + self.perp_margin + self._perp_upnl()
