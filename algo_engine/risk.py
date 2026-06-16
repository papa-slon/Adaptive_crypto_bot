"""Risk management — the part that actually keeps you alive.

The RiskManager is the single authority on:
  * position SIZE (fixed fractional risk: you can only lose `risk_pct` of
    equity if the stop is hit),
  * whether a new entry is ALLOWED right now (daily loss limit),
  * the global KILL-SWITCH (max drawdown from peak equity).

Both the backtester and the live loop route every entry through this class,
so the rules you test are exactly the rules that trade.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class RiskConfig:
    risk_pct: float = 0.005          # 0.5% of equity risked per trade
    max_leverage: float = 5.0        # notional cap = equity * max_leverage
    daily_loss_limit: float = -0.06  # halt NEW entries after -6% on the day
    max_drawdown: float = -0.25      # KILL everything at -25% from peak equity
    min_notional: float = 5.0        # exchange minimum (USDT); skip if below
    qty_step: float = 0.0            # 0 = no rounding (set per-symbol in live)


@dataclass
class SizeResult:
    allowed: bool
    qty: float = 0.0
    notional: float = 0.0
    reason: str = ""


class RiskManager:
    def __init__(self, cfg: RiskConfig, initial_equity: float) -> None:
        self.cfg = cfg
        self.initial_equity = initial_equity
        self.peak_equity = initial_equity
        self.day_start_equity = initial_equity
        self.current_day: str | None = None
        self.killed = False
        self.kill_reason = ""

    # ----- equity bookkeeping -------------------------------------------------
    def mark_equity(self, equity: float, day_key: str | None = None) -> None:
        """Update peak/daily anchors. Call once per bar (or tick) with the
        latest equity. `day_key` is e.g. the UTC date string for daily reset."""
        if day_key is not None and day_key != self.current_day:
            self.current_day = day_key
            self.day_start_equity = equity
        self.peak_equity = max(self.peak_equity, equity)

        dd = (equity / self.peak_equity) - 1.0 if self.peak_equity > 0 else 0.0
        if not self.killed and dd <= self.cfg.max_drawdown:
            self.killed = True
            self.kill_reason = f"max drawdown hit: {dd:.2%} <= {self.cfg.max_drawdown:.2%}"

    def day_pnl_pct(self, equity: float) -> float:
        if self.day_start_equity <= 0:
            return 0.0
        return (equity / self.day_start_equity) - 1.0

    def can_enter(self, equity: float) -> tuple[bool, str]:
        if self.killed:
            return False, f"KILL-SWITCH active ({self.kill_reason})"
        if self.day_pnl_pct(equity) <= self.cfg.daily_loss_limit:
            return False, f"daily loss limit ({self.day_pnl_pct(equity):.2%})"
        return True, ""

    # ----- sizing -------------------------------------------------------------
    def size(self, equity: float, entry: float, stop: float) -> SizeResult:
        ok, reason = self.can_enter(equity)
        if not ok:
            return SizeResult(False, reason=reason)

        stop_dist = abs(entry - stop)
        if stop_dist <= 0 or entry <= 0:
            return SizeResult(False, reason="invalid stop distance")

        risk_amount = equity * self.cfg.risk_pct
        qty = risk_amount / stop_dist

        # leverage / notional cap
        max_notional = equity * self.cfg.max_leverage
        notional = qty * entry
        if notional > max_notional:
            qty = max_notional / entry
            notional = qty * entry

        if self.cfg.qty_step > 0:
            steps = int(qty / self.cfg.qty_step)
            qty = steps * self.cfg.qty_step
            notional = qty * entry

        if qty <= 0 or notional < self.cfg.min_notional:
            return SizeResult(False, reason=f"below min notional ({notional:.2f})")

        return SizeResult(True, qty=qty, notional=notional)
