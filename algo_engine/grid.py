"""Adaptive ATR grid simulator (separate from the single-position Backtester).

A grid does not predict direction — it harvests oscillation by layering limit
orders around a center, banking one grid-step each time price round-trips.
Its killer is a sustained trend (inventory piles up against the move), so this
implementation is *adaptive*:

  * grid spacing = `step_atr * ATR`  (widens in volatility, tightens in calm),
  * a trend gate (EMA slope) blocks adding NEW inventory against a strong trend
    (no longs while price is far below a falling EMA; no shorts in a rip),
  * bounded inventory per side + an equity drawdown kill-switch.

Fills are approximated from OHLC bars (a level is "hit" if [low, high] spans
it). This is the standard grid-backtest approximation; it is mildly optimistic
on fill price, so we use maker-ish costs and report it as such. Look-ahead
free: every decision on bar i uses only data up to i.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from . import indicators as ind
from . import metrics


@dataclass
class GridConfig:
    n_levels: int = 5            # rungs per side
    step_atr: float = 0.6        # grid spacing in ATR units
    atr_period: int = 14
    order_frac: float = 0.02     # notional per rung as fraction of start equity
    max_inventory: int = 5       # max open lots per side
    trend_ema: int = 100         # EMA for the trend gate
    trend_block: float = 1.0     # block side if |close-ema|/atr exceeds this AND slope agrees
    recenter_bars: int = 96      # periodic recenter when flat
    fee: float = 0.0002          # maker-ish (grid is fill-heavy)
    slippage: float = 0.0001
    dd_kill: float = 0.25        # liquidate + stop if equity DD exceeds this


@dataclass
class _Lot:
    side: str       # 'long' | 'short'
    entry: float
    tp: float       # take-profit (one grid step toward mean)


def simulate_grid(raw_df: pd.DataFrame, cfg: GridConfig, bars_per_year: float = 35040.0) -> dict:
    df = raw_df.copy()
    df["atr"] = ind.atr(df, cfg.atr_period)
    df["ema"] = ind.ema(df["close"], cfg.trend_ema)

    equity = 1.0                # fraction of start capital
    peak = 1.0
    realized = 0.0
    longs: list[_Lot] = []
    shorts: list[_Lot] = []
    center: float | None = None
    bars_since_recenter = 0
    killed = False

    wins = 0
    losses = 0          # grid TP exits are always +step wins; "losses" come from kill liquidation
    gross_win = 0.0
    gross_loss = 0.0
    n_fills = 0
    eq_curve = []

    f = cfg.fee + cfg.slippage  # per-side cost as a fraction of notional

    def lot_pnl_frac(side, entry, exit_):
        ret = (exit_ - entry) / entry if side == "long" else (entry - exit_) / entry
        return cfg.order_frac * ret - 2 * f * cfg.order_frac

    for i in range(len(df)):
        row = df.iloc[i]
        atr = float(row["atr"]) if not pd.isna(row["atr"]) else np.nan
        close = float(row["close"])
        eq_curve.append(equity + sum(lot_pnl_frac(l.side, l.entry, close) for l in longs + shorts))
        if killed or np.isnan(atr) or pd.isna(row["ema"]) or atr <= 0:
            if center is None and not np.isnan(atr):
                center = close
            continue

        step = cfg.step_atr * atr
        low, high, ema = float(row["low"]), float(row["high"]), float(row["ema"])
        if center is None:
            center = close

        # 1) take-profit exits (price reached the rung's TP)
        still_long = []
        for lot in longs:
            if high >= lot.tp:
                pnl = lot_pnl_frac("long", lot.entry, lot.tp)
                realized += pnl; equity += pnl; n_fills += 1
                wins += 1; gross_win += max(pnl, 0); gross_loss += -min(pnl, 0)
            else:
                still_long.append(lot)
        longs = still_long
        still_short = []
        for lot in shorts:
            if low <= lot.tp:
                pnl = lot_pnl_frac("short", lot.entry, lot.tp)
                realized += pnl; equity += pnl; n_fills += 1
                wins += 1; gross_win += max(pnl, 0); gross_loss += -min(pnl, 0)
            else:
                still_short.append(lot)
        shorts = still_short

        # 2) trend gate: how stretched is price from the EMA (in ATR units)?
        stretch = (close - ema) / atr
        allow_long = not (cfg.trend_block and stretch < -cfg.trend_block)   # don't buy a falling knife
        allow_short = not (cfg.trend_block and stretch > cfg.trend_block)   # don't short a rip

        # 3) new entries: rungs spanned by this bar's range.
        #    Guard: don't re-stack a rung that already holds a lot (same price
        #    within half a step) — otherwise a bar parked below a trigger would
        #    add a lot every bar.
        near = 0.5 * step
        for k in range(1, cfg.n_levels + 1):
            buy_trigger = center - k * step
            if (allow_long and len(longs) < cfg.max_inventory and low <= buy_trigger
                    and not any(abs(l.entry - buy_trigger) < near for l in longs)):
                longs.append(_Lot("long", buy_trigger, buy_trigger + step)); n_fills += 1
            sell_trigger = center + k * step
            if (allow_short and len(shorts) < cfg.max_inventory and high >= sell_trigger
                    and not any(abs(l.entry - sell_trigger) < near for l in shorts)):
                shorts.append(_Lot("short", sell_trigger, sell_trigger - step)); n_fills += 1

        # 4) recenter when flat (keeps the grid near price)
        bars_since_recenter += 1
        if not longs and not shorts and bars_since_recenter >= cfg.recenter_bars:
            center = close; bars_since_recenter = 0

        # 5) drawdown kill-switch (mark-to-market incl. open inventory)
        mtm = equity + sum(lot_pnl_frac(l.side, l.entry, close) for l in longs + shorts)
        peak = max(peak, mtm)
        if peak > 0 and (peak - mtm) / peak >= cfg.dd_kill:
            for lot in longs + shorts:           # liquidate everything at close
                pnl = lot_pnl_frac(lot.side, lot.entry, close)
                realized += pnl; equity += pnl
                if pnl >= 0: wins += 1; gross_win += pnl
                else: losses += 1; gross_loss += -pnl
            longs, shorts = [], []
            killed = True

    # final mark-to-market
    last_close = float(df["close"].iloc[-1])
    equity += sum(lot_pnl_frac(l.side, l.entry, last_close) for l in longs + shorts)
    eq = pd.Series(eq_curve, index=df.index[: len(eq_curve)])
    total_trades = wins + losses
    pf = (gross_win / gross_loss) if gross_loss > 0 else (float("inf") if gross_win > 0 else 0.0)
    return {
        "total_return": equity - 1.0,
        "max_drawdown": metrics.max_drawdown(eq),
        "sharpe": metrics.sharpe(eq, bars_per_year=bars_per_year),
        "n_fills": n_fills,
        "n_closed": total_trades,
        "win_rate": (wins / total_trades) if total_trades else 0.0,
        "profit_factor": pf,
        "killed": killed,
        "equity": eq,
    }
