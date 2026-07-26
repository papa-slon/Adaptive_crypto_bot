from __future__ import annotations

import pandas as pd

from .. import indicators as ind
from .base import PositionView, Signal, Strategy


class TrendBreakout(Strategy):
    """Donchian breakout, filtered by trend (EMA) and trend strength (ADX).

    Logic (all on closed bars):
      * Long when close breaks above the prior `channel`-bar high AND the
        fast EMA is above the slow EMA AND ADX shows a real trend.
      * Short is the mirror.
      * Protective stop = entry ∓ `atr_mult` * ATR (volatility-scaled).
      * Exit when price closes back below/above the fast EMA (trend lost),
        or when the stop is hit (handled by the backtester / risk layer).

    This is a "cut losers fast, ride trends" design — the survivable archetype
    on 1–15m timeframes. It will have a LOW win-rate by nature; its edge, if
    any, comes from the average winner being bigger than the average loser.
    """

    name = "trend_breakout"

    def __init__(
        self,
        channel: int = 20,
        ema_fast: int = 21,
        ema_slow: int = 100,
        adx_period: int = 14,
        adx_min: float = 18.0,
        atr_period: int = 14,
        atr_mult: float = 1.5,
    ) -> None:
        self.channel = channel
        self.ema_fast = ema_fast
        self.ema_slow = ema_slow
        self.adx_period = adx_period
        self.adx_min = adx_min
        self.atr_period = atr_period
        self.atr_mult = atr_mult
        self.warmup = max(ema_slow, channel, adx_period, atr_period) + 5

    def prepare(self, df: pd.DataFrame) -> pd.DataFrame:
        out = df.copy()
        out["ema_fast"] = ind.ema(out["close"], self.ema_fast)
        out["ema_slow"] = ind.ema(out["close"], self.ema_slow)
        out["adx"] = ind.adx(out, self.adx_period)
        out["atr"] = ind.atr(out, self.atr_period)
        upper, lower = ind.donchian(out, self.channel)
        out["dc_upper"] = upper
        out["dc_lower"] = lower
        return out

    def signal(self, df: pd.DataFrame, i: int, position: PositionView | None) -> Signal:
        row = df.iloc[i]
        if pd.isna(row.get("atr")) or pd.isna(row.get("dc_upper")) or pd.isna(row.get("ema_slow")):
            return Signal("none", reason="warmup")

        atr = float(row["atr"])
        close = float(row["close"])
        up_trend = row["ema_fast"] > row["ema_slow"]
        down_trend = row["ema_fast"] < row["ema_slow"]
        strong = row["adx"] >= self.adx_min

        broke_up = close > row["dc_upper"]
        broke_down = close < row["dc_lower"]

        # --- Direction-aware exits first (only when holding) ---
        if position is not None and position.side == "long" and close < row["ema_fast"]:
            return Signal("flat", reason="lost ema (long exit)")
        if position is not None and position.side == "short" and close > row["ema_fast"]:
            return Signal("flat", reason="lost ema (short exit)")

        # --- Entries (only when flat) ---
        if position is None:
            if broke_up and up_trend and strong:
                return Signal(
                    "long",
                    stop=close - self.atr_mult * atr,
                    reason=f"breakout up adx={row['adx']:.0f}",
                )
            if broke_down and down_trend and strong:
                return Signal(
                    "short",
                    stop=close + self.atr_mult * atr,
                    reason=f"breakout down adx={row['adx']:.0f}",
                )

        return Signal("none")
