"""Event-driven backtester — realistic and look-ahead free.

Core honesty rules (the ones that separate a real backtest from a fantasy):
  * A decision is made at the CLOSE of bar i and executed at the OPEN of bar
    i+1. You can never trade on information you didn't have yet.
  * Stops are checked INTRABAR using each bar's high/low, and a gap THROUGH the
    stop fills at the (worse) open price, not the stop price.
  * Every fill pays a taker fee and a slippage haircut. Returns are NET.
  * One position at a time. Sizing always goes through the RiskManager, so the
    0.5%-risk / daily-loss / kill-switch rules are enforced in the test too.
"""
from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from . import metrics
from .risk import RiskConfig, RiskManager
from .strategies.base import PositionView, Strategy


@dataclass
class BacktestConfig:
    initial_equity: float = 10_000.0
    fee: float = 0.00055        # Bybit linear taker ~0.055% per side
    slippage: float = 0.0005    # 5 bps per fill
    bars_per_year: float = 105_120.0  # default = 5m bars; override per TF


def _buy_fill(px: float, slip: float) -> float:
    return px * (1.0 + slip)


def _sell_fill(px: float, slip: float) -> float:
    return px * (1.0 - slip)


class Backtester:
    def __init__(self, strategy: Strategy, risk: RiskConfig, cfg: BacktestConfig) -> None:
        self.strategy = strategy
        self.risk_cfg = risk
        self.cfg = cfg

    def run(self, raw_df: pd.DataFrame) -> tuple[metrics.Report, list[metrics.Trade], pd.Series]:
        df = self.strategy.prepare(raw_df)
        n = len(df)
        warmup = self.strategy.warmup
        fee, slip = self.cfg.fee, self.cfg.slippage

        rm = RiskManager(self.risk_cfg, self.cfg.initial_equity)
        realized = self.cfg.initial_equity

        position: dict | None = None
        pending: tuple[str, object] | None = None  # ("enter", Signal) | ("exit", reason)
        trades: list[metrics.Trade] = []
        eq_times: list[pd.Timestamp] = []
        eq_values: list[float] = []

        def close_position(exit_fill: float, exit_time, reason: str) -> None:
            nonlocal realized, position
            assert position is not None
            qty = position["qty"]
            entry_fill = position["entry"]
            if position["side"] == "long":
                gross = (exit_fill - entry_fill) * qty
            else:
                gross = (entry_fill - exit_fill) * qty
            exit_fee = fee * exit_fill * qty
            net = gross - position["entry_fee"] - exit_fee
            realized += net
            entry_notional = entry_fill * qty
            trades.append(
                metrics.Trade(
                    side=position["side"],
                    entry_time=position["entry_time"],
                    exit_time=exit_time,
                    entry=entry_fill,
                    exit=exit_fill,
                    qty=qty,
                    pnl=net,
                    pnl_pct=(net / entry_notional) if entry_notional else 0.0,
                    bars_held=position["bars_held"],
                    reason=reason,
                )
            )
            position = None

        for i in range(warmup, n):
            bar = df.iloc[i]
            ts = df.index[i]

            # (A) Execute the action decided on the previous bar's close.
            if pending is not None:
                kind = pending[0]
                if kind == "exit" and position is not None:
                    if position["side"] == "long":
                        close_position(_sell_fill(bar["open"], slip), ts, str(pending[1]))
                    else:
                        close_position(_buy_fill(bar["open"], slip), ts, str(pending[1]))
                elif kind == "enter" and position is None:
                    sig = pending[1]
                    side = sig.action
                    entry_fill = _buy_fill(bar["open"], slip) if side == "long" else _sell_fill(bar["open"], slip)
                    sz = rm.size(realized, entry_fill, sig.stop)
                    if sz.allowed:
                        entry_fee = fee * entry_fill * sz.qty
                        realized -= entry_fee
                        position = {
                            "side": side,
                            "entry": entry_fill,
                            "qty": sz.qty,
                            "stop": sig.stop,
                            "entry_time": ts,
                            "entry_idx": i,
                            "entry_fee": entry_fee,
                            "bars_held": 0,
                        }
                pending = None

            # (B) Intrabar stop check on the open position (this bar's range).
            if position is not None:
                position["bars_held"] = i - position["entry_idx"]
                stop = position["stop"]
                if position["side"] == "long" and bar["low"] <= stop:
                    ref = min(stop, bar["open"])  # gap-through fills worse
                    close_position(_sell_fill(ref, slip), ts, "stop")
                elif position["side"] == "short" and bar["high"] >= stop:
                    ref = max(stop, bar["open"])
                    close_position(_buy_fill(ref, slip), ts, "stop")

            # (C) Mark-to-market equity at close; update risk anchors.
            unrealized = 0.0
            if position is not None:
                if position["side"] == "long":
                    unrealized = (bar["close"] - position["entry"]) * position["qty"]
                else:
                    unrealized = (position["entry"] - bar["close"]) * position["qty"]
            mark = realized + unrealized
            rm.mark_equity(mark, day_key=str(ts.date()) if hasattr(ts, "date") else None)
            eq_times.append(ts)
            eq_values.append(mark)

            # (D) Decide next action at the close of bar i (causal).
            if rm.killed:
                if position is not None:
                    pending = ("exit", "kill-switch")  # flatten next open
                continue

            posview = None
            if position is not None:
                posview = PositionView(
                    side=position["side"],
                    entry=position["entry"],
                    stop=position["stop"],
                    bars_held=position["bars_held"],
                )
            sig = self.strategy.signal(df, i, posview)
            if position is not None and sig.action == "flat":
                pending = ("exit", sig.reason or "signal exit")
            elif position is None and sig.action in ("long", "short") and sig.stop is not None:
                pending = ("enter", sig)

        equity_curve = pd.Series(eq_values, index=pd.DatetimeIndex(eq_times), name="equity")
        report = metrics.build_report(
            trades, equity_curve, self.cfg.initial_equity, self.cfg.bars_per_year
        )
        report.extra["killed"] = rm.killed
        report.extra["kill_reason"] = rm.kill_reason
        return report, trades, equity_curve


def bars_per_year_for(interval_minutes: float) -> float:
    return 365.0 * 24.0 * 60.0 / interval_minutes
