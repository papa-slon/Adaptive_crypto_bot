from __future__ import annotations

import pandas as pd

from .. import indicators as ind
from .base import PositionView, Signal, Strategy


class MeanReversion(Strategy):
    """Fade stretched moves back to a moving average.

    Logic (all on closed bars):
      * Compute the z-score of close vs its EMA (how many std-devs stretched).
      * Long when z <= -z_entry (oversold) AND price is still inside the
        longer-term regime band (don't catch a falling knife in a hard
        downtrend: require close above the slow EMA's regime floor).
      * Short is the mirror.
      * Exit when price reverts to the mean (z near 0), the stop is hit, or a
        hard time-stop (`max_hold` bars) elapses — mean-reversion trades that
        don't revert quickly are usually wrong.

    High win-rate, but the tail risk is real: a fade that keeps going against
    you is the classic blow-up. That is exactly why the stop + the 0.5% risk
    cap + the daily-loss kill-switch matter more here than anywhere.
    """

    name = "mean_reversion"

    def __init__(
        self,
        ema_period: int = 20,
        z_period: int = 100,
        z_entry: float = 2.2,
        z_exit: float = 0.3,
        regime_ema: int = 200,
        atr_period: int = 14,
        atr_mult: float = 1.2,
        max_hold: int = 24,
    ) -> None:
        self.ema_period = ema_period
        self.z_period = z_period
        self.z_entry = z_entry
        self.z_exit = z_exit
        self.regime_ema = regime_ema
        self.atr_period = atr_period
        self.atr_mult = atr_mult
        self.max_hold = max_hold
        self.warmup = max(z_period, regime_ema, atr_period) + 5

    def prepare(self, df: pd.DataFrame) -> pd.DataFrame:
        out = df.copy()
        out["ema"] = ind.ema(out["close"], self.ema_period)
        out["regime"] = ind.ema(out["close"], self.regime_ema)
        out["atr"] = ind.atr(out, self.atr_period)
        # z-score of the close-to-EMA spread vs its own recent distribution
        spread = out["close"] - out["ema"]
        out["z"] = ind.rolling_zscore(spread, self.z_period)
        return out

    def signal(self, df: pd.DataFrame, i: int, position: PositionView | None) -> Signal:
        row = df.iloc[i]
        if pd.isna(row.get("z")) or pd.isna(row.get("atr")) or pd.isna(row.get("regime")):
            return Signal("none", reason="warmup")

        z = float(row["z"])
        close = float(row["close"])
        atr = float(row["atr"])

        # --- Direction-aware exits first ---
        if position is not None and position.side == "long":
            if z >= -self.z_exit:
                return Signal("flat", reason=f"reverted z={z:.2f}")
            if position.bars_held >= self.max_hold:
                return Signal("flat", reason="time stop")
            return Signal("none")
        if position is not None and position.side == "short":
            if z <= self.z_exit:
                return Signal("flat", reason=f"reverted z={z:.2f}")
            if position.bars_held >= self.max_hold:
                return Signal("flat", reason="time stop")
            return Signal("none")

        # --- Entries (flat only) ---
        above_regime = close >= row["regime"]
        below_regime = close <= row["regime"]
        if z <= -self.z_entry and above_regime:
            return Signal("long", stop=close - self.atr_mult * atr, reason=f"oversold z={z:.2f}")
        if z >= self.z_entry and below_regime:
            return Signal("short", stop=close + self.atr_mult * atr, reason=f"overbought z={z:.2f}")

        return Signal("none")
