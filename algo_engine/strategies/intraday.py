"""Smarter intraday strategies for 5-15m, where naive trend/mean-rev failed.

Each is well-motivated and trades LESS than the naive pair (fewer, higher-
quality entries -> less fee drag, the killer at low TF). All look-ahead free.
"""
from __future__ import annotations

import pandas as pd

from .. import indicators as ind
from .base import PositionView, Signal, Strategy


class SqueezeBreakout(Strategy):
    """Volatility-contraction breakout (Bollinger inside Keltner = 'squeeze').

    Only fires when volatility was compressed and then expands — catching the
    impulse leg while sitting out the chop. Direction from short-term momentum.
    """

    name = "squeeze_breakout"

    def __init__(self, period=20, bb_k=2.0, kc_k=1.5, mom=5, atr_period=14, atr_mult=1.6):
        self.period, self.bb_k, self.kc_k = period, bb_k, kc_k
        self.mom, self.atr_period, self.atr_mult = mom, atr_period, atr_mult
        self.warmup = max(period, atr_period, mom) + 5

    def prepare(self, df):
        out = df.copy()
        _, bu, bl = ind.bollinger(out["close"], self.period, self.bb_k)
        kmid, ku, kl = ind.keltner(out, self.period, self.kc_k)
        out["kc_mid"], out["atr"] = kmid, ind.atr(out, self.atr_period)
        out["sq_on"] = (bu < ku) & (bl > kl)
        out["mom"] = out["close"] - out["close"].shift(self.mom)
        return out

    def signal(self, df, i, position):
        row = df.iloc[i]
        if pd.isna(row.get("atr")) or pd.isna(row.get("kc_mid")) or i < 1:
            return Signal("none", reason="warmup")
        close, atr = float(row["close"]), float(row["atr"])
        if position is not None and position.side == "long" and close < row["kc_mid"]:
            return Signal("flat", reason="lost channel mid")
        if position is not None and position.side == "short" and close > row["kc_mid"]:
            return Signal("flat", reason="lost channel mid")
        if position is None:
            released = bool(df.iloc[i - 1]["sq_on"]) and not bool(row["sq_on"])
            if released and row["mom"] > 0 and close > row["kc_mid"]:
                return Signal("long", stop=close - self.atr_mult * atr, reason="squeeze release up")
            if released and row["mom"] < 0 and close < row["kc_mid"]:
                return Signal("short", stop=close + self.atr_mult * atr, reason="squeeze release down")
        return Signal("none")


class TrendPullback(Strategy):
    """Buy pullbacks to the fast EMA inside a stacked-EMA trend (continuation).

    Higher win-rate than raw breakout: you enter WITH an established trend on a
    dip, not on the extension.
    """

    name = "trend_pullback"

    def __init__(self, ema_fast=8, ema_mid=21, ema_slow=50, rsi_period=14,
                 rsi_cap=72.0, atr_period=14, atr_mult=1.5):
        self.ema_fast, self.ema_mid, self.ema_slow = ema_fast, ema_mid, ema_slow
        self.rsi_period, self.rsi_cap = rsi_period, rsi_cap
        self.atr_period, self.atr_mult = atr_period, atr_mult
        self.warmup = max(ema_slow, rsi_period, atr_period) + 5

    def prepare(self, df):
        out = df.copy()
        out["ef"] = ind.ema(out["close"], self.ema_fast)
        out["em"] = ind.ema(out["close"], self.ema_mid)
        out["es"] = ind.ema(out["close"], self.ema_slow)
        out["rsi"] = ind.rsi(out["close"], self.rsi_period)
        out["atr"] = ind.atr(out, self.atr_period)
        return out

    def signal(self, df, i, position):
        row = df.iloc[i]
        if pd.isna(row.get("es")) or pd.isna(row.get("atr")) or pd.isna(row.get("rsi")):
            return Signal("none", reason="warmup")
        close, atr = float(row["close"]), float(row["atr"])
        long_regime = row["ef"] > row["em"] > row["es"]
        short_regime = row["ef"] < row["em"] < row["es"]
        if position is not None and position.side == "long" and close < row["em"]:
            return Signal("flat", reason="lost mid ema")
        if position is not None and position.side == "short" and close > row["em"]:
            return Signal("flat", reason="lost mid ema")
        if position is None:
            if long_regime and row["low"] <= row["ef"] and close > row["ef"] and row["rsi"] < self.rsi_cap:
                return Signal("long", stop=close - self.atr_mult * atr, reason="pullback long")
            if short_regime and row["high"] >= row["ef"] and close < row["ef"] and row["rsi"] > (100 - self.rsi_cap):
                return Signal("short", stop=close + self.atr_mult * atr, reason="pullback short")
        return Signal("none")


class VwapReversion(Strategy):
    """Fade stretched moves away from the intraday (session) VWAP, back to it."""

    name = "vwap_reversion"

    def __init__(self, z_period=50, z_entry=2.0, atr_period=14, atr_mult=1.4, max_hold=18):
        self.z_period, self.z_entry = z_period, z_entry
        self.atr_period, self.atr_mult, self.max_hold = atr_period, atr_mult, max_hold
        self.warmup = max(z_period, atr_period) + 5

    def prepare(self, df):
        out = df.copy()
        out["vwap"] = ind.session_vwap(out)
        out["atr"] = ind.atr(out, self.atr_period)
        dist = out["close"] - out["vwap"]
        sd = dist.rolling(self.z_period, min_periods=self.z_period).std(ddof=0)
        out["z"] = dist / sd.replace(0.0, float("nan"))
        return out

    def signal(self, df, i, position):
        row = df.iloc[i]
        if pd.isna(row.get("z")) or pd.isna(row.get("atr")) or pd.isna(row.get("vwap")):
            return Signal("none", reason="warmup")
        close, atr, z = float(row["close"]), float(row["atr"]), float(row["z"])
        if position is not None and position.side == "long":
            if close >= row["vwap"] or position.bars_held >= self.max_hold:
                return Signal("flat", reason="back to vwap / time")
            return Signal("none")
        if position is not None and position.side == "short":
            if close <= row["vwap"] or position.bars_held >= self.max_hold:
                return Signal("flat", reason="back to vwap / time")
            return Signal("none")
        if position is None:
            if z <= -self.z_entry:
                return Signal("long", stop=close - self.atr_mult * atr, reason="below vwap")
            if z >= self.z_entry:
                return Signal("short", stop=close + self.atr_mult * atr, reason="above vwap")
        return Signal("none")


class RangeRejection(Strategy):
    """Gerchik-style false-breakout: price pokes through a level and snaps back.

    Long: bar dips below recent support but CLOSES back above it (failed
    breakdown -> trapped sellers). Short mirrors at resistance. Tight stop just
    beyond the rejected wick; target the opposite level.
    """

    name = "range_rejection"

    def __init__(self, lookback=30, atr_period=14, wick_buffer=0.1, max_hold=24):
        self.lookback, self.atr_period = lookback, atr_period
        self.wick_buffer, self.max_hold = wick_buffer, max_hold
        self.warmup = max(lookback, atr_period) + 5

    def prepare(self, df):
        out = df.copy()
        res, sup = ind.rolling_high_low(out, self.lookback)
        out["res"], out["sup"] = res, sup
        out["atr"] = ind.atr(out, self.atr_period)
        return out

    def signal(self, df, i, position):
        row = df.iloc[i]
        if pd.isna(row.get("res")) or pd.isna(row.get("sup")) or pd.isna(row.get("atr")):
            return Signal("none", reason="warmup")
        close, atr = float(row["close"]), float(row["atr"])
        if position is not None and position.side == "long":
            if close >= row["res"] or position.bars_held >= self.max_hold:
                return Signal("flat", reason="hit resistance / time")
            return Signal("none")
        if position is not None and position.side == "short":
            if close <= row["sup"] or position.bars_held >= self.max_hold:
                return Signal("flat", reason="hit support / time")
            return Signal("none")
        if position is None:
            if row["low"] < row["sup"] and close > row["sup"]:
                return Signal("long", stop=float(row["low"]) - self.wick_buffer * atr, reason="false breakdown")
            if row["high"] > row["res"] and close < row["res"]:
                return Signal("short", stop=float(row["high"]) + self.wick_buffer * atr, reason="false breakout")
        return Signal("none")
