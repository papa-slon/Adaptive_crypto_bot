"""Trading strategies.

Each strategy is pure decision logic: it computes indicators on closed bars
and emits a desired position state. It never sizes orders, never talks to an
exchange, never touches risk limits — that is the RiskManager's job. This
separation is what lets the SAME strategy run identically in backtest and live.
"""
from __future__ import annotations

from .base import Signal, Strategy
from .trend_breakout import TrendBreakout
from .mean_reversion import MeanReversion

REGISTRY: dict[str, type[Strategy]] = {
    "trend_breakout": TrendBreakout,
    "mean_reversion": MeanReversion,
}


def build(name: str, **params) -> Strategy:
    if name not in REGISTRY:
        raise KeyError(f"unknown strategy '{name}'. known: {sorted(REGISTRY)}")
    return REGISTRY[name](**params)


__all__ = ["Signal", "Strategy", "TrendBreakout", "MeanReversion", "REGISTRY", "build"]
