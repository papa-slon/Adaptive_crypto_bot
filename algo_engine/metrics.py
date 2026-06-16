"""Performance metrics for a list of closed trades + an equity curve.

Deliberately honest: returns are NET of fees and slippage (the backtester
already subtracts them), and the metrics that matter most on small timeframes
— max drawdown, profit factor, expectancy — are front and centre.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np
import pandas as pd


@dataclass
class Trade:
    side: str
    entry_time: pd.Timestamp
    exit_time: pd.Timestamp
    entry: float
    exit: float
    qty: float
    pnl: float           # net of fees/slippage, in quote currency (USDT)
    pnl_pct: float       # net return on the trade's notional
    bars_held: int
    reason: str


@dataclass
class Report:
    n_trades: int = 0
    win_rate: float = 0.0
    profit_factor: float = 0.0
    expectancy: float = 0.0          # avg net PnL per trade (USDT)
    total_return: float = 0.0        # final/initial - 1
    max_drawdown: float = 0.0        # most negative equity dip from peak
    sharpe: float = 0.0              # annualized, from per-bar equity returns
    avg_win: float = 0.0
    avg_loss: float = 0.0
    final_equity: float = 0.0
    initial_equity: float = 0.0
    extra: dict = field(default_factory=dict)

    def pretty(self) -> str:
        return (
            f"trades={self.n_trades}  win%={self.win_rate*100:5.1f}  "
            f"PF={self.profit_factor:4.2f}  exp={self.expectancy:+.2f}USDT  "
            f"ret={self.total_return*100:+6.1f}%  maxDD={self.max_drawdown*100:5.1f}%  "
            f"Sharpe={self.sharpe:4.2f}  eq={self.final_equity:,.0f}"
        )


def max_drawdown(equity: pd.Series) -> float:
    if equity.empty:
        return 0.0
    running_peak = equity.cummax()
    dd = equity / running_peak - 1.0
    return float(dd.min())


def sharpe(equity: pd.Series, bars_per_year: float) -> float:
    """Annualized Sharpe from per-bar equity returns (risk-free = 0)."""
    rets = equity.pct_change().dropna()
    if rets.empty or rets.std(ddof=0) == 0:
        return 0.0
    return float(rets.mean() / rets.std(ddof=0) * math.sqrt(bars_per_year))


def build_report(
    trades: list[Trade],
    equity_curve: pd.Series,
    initial_equity: float,
    bars_per_year: float,
) -> Report:
    rep = Report(initial_equity=initial_equity)
    rep.n_trades = len(trades)
    rep.final_equity = float(equity_curve.iloc[-1]) if len(equity_curve) else initial_equity
    rep.total_return = rep.final_equity / initial_equity - 1.0 if initial_equity else 0.0
    rep.max_drawdown = max_drawdown(equity_curve)
    rep.sharpe = sharpe(equity_curve, bars_per_year)

    if not trades:
        return rep

    pnls = np.array([t.pnl for t in trades], dtype=float)
    wins = pnls[pnls > 0]
    losses = pnls[pnls < 0]
    rep.win_rate = len(wins) / len(pnls)
    gross_win = wins.sum()
    gross_loss = -losses.sum()
    rep.profit_factor = float(gross_win / gross_loss) if gross_loss > 0 else float("inf")
    rep.expectancy = float(pnls.mean())
    rep.avg_win = float(wins.mean()) if len(wins) else 0.0
    rep.avg_loss = float(losses.mean()) if len(losses) else 0.0
    return rep
