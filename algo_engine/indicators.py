"""Vectorized, look-ahead-free technical indicators (pandas/numpy).

Every function takes a DataFrame/Series of CLOSED bars and returns a Series
aligned to the input index. No value at bar i ever depends on bar i+1.
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def ema(series: pd.Series, period: int) -> pd.Series:
    """Exponential moving average."""
    return series.ewm(span=period, adjust=False, min_periods=period).mean()


def sma(series: pd.Series, period: int) -> pd.Series:
    return series.rolling(period, min_periods=period).mean()


def true_range(df: pd.DataFrame) -> pd.Series:
    high, low, close = df["high"], df["low"], df["close"]
    prev_close = close.shift(1)
    tr = pd.concat(
        [
            high - low,
            (high - prev_close).abs(),
            (low - prev_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    return tr


def atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """Wilder's ATR (RMA of true range)."""
    tr = true_range(df)
    # Wilder smoothing == EMA with alpha = 1/period
    return tr.ewm(alpha=1.0 / period, adjust=False, min_periods=period).mean()


def rsi(series: pd.Series, period: int = 14) -> pd.Series:
    delta = series.diff()
    gain = delta.clip(lower=0.0)
    loss = (-delta).clip(lower=0.0)
    avg_gain = gain.ewm(alpha=1.0 / period, adjust=False, min_periods=period).mean()
    avg_loss = loss.ewm(alpha=1.0 / period, adjust=False, min_periods=period).mean()
    rs = avg_gain / avg_loss.replace(0.0, np.nan)
    out = 100.0 - (100.0 / (1.0 + rs))
    # When avg_loss == 0 the asset only went up -> RSI 100.
    out = out.where(avg_loss != 0.0, 100.0)
    return out


def rolling_zscore(series: pd.Series, period: int) -> pd.Series:
    """Z-score of `series` vs its own rolling mean/std (population std)."""
    mean = series.rolling(period, min_periods=period).mean()
    std = series.rolling(period, min_periods=period).std(ddof=0)
    return (series - mean) / std.replace(0.0, np.nan)


def donchian(df: pd.DataFrame, period: int) -> tuple[pd.Series, pd.Series]:
    """Donchian channel based on CLOSED bars only (shifted by 1).

    Returns (upper, lower) where the level at bar i is the highest high /
    lowest low of the `period` bars ENDING at bar i-1. This is what you must
    compare bar i's price against to detect a breakout without look-ahead.
    """
    upper = df["high"].rolling(period, min_periods=period).max().shift(1)
    lower = df["low"].rolling(period, min_periods=period).min().shift(1)
    return upper, lower


def bollinger(series: pd.Series, period: int = 20, k: float = 2.0):
    """Bollinger Bands -> (mid, upper, lower). Causal (rolling, ends at i)."""
    mid = series.rolling(period, min_periods=period).mean()
    sd = series.rolling(period, min_periods=period).std(ddof=0)
    return mid, mid + k * sd, mid - k * sd


def keltner(df: pd.DataFrame, period: int = 20, k: float = 1.5):
    """Keltner Channels -> (mid, upper, lower) using EMA + ATR."""
    mid = ema(df["close"], period)
    rng = atr(df, period)
    return mid, mid + k * rng, mid - k * rng


def session_vwap(df: pd.DataFrame) -> pd.Series:
    """Intraday VWAP that resets each UTC day. Cumulative up to bar i (causal)."""
    tp = (df["high"] + df["low"] + df["close"]) / 3.0
    day = df.index.tz_convert("UTC").date if df.index.tz is not None else df.index.date
    grp = pd.Series(day, index=df.index)
    pv = (tp * df["volume"]).groupby(grp).cumsum()
    vv = df["volume"].groupby(grp).cumsum().replace(0.0, np.nan)
    return pv / vv


def rolling_high_low(df: pd.DataFrame, period: int):
    """Prior-window swing level (shifted by 1) -> (resistance, support).

    Level at bar i is built from the `period` bars ENDING at i-1, so comparing
    bar i's price to it detects a poke/breakout without look-ahead.
    """
    res = df["high"].rolling(period, min_periods=period).max().shift(1)
    sup = df["low"].rolling(period, min_periods=period).min().shift(1)
    return res, sup


def adx(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """Average Directional Index — trend-strength filter (0..100)."""
    up = df["high"].diff()
    down = -df["low"].diff()
    plus_dm = np.where((up > down) & (up > 0), up, 0.0)
    minus_dm = np.where((down > up) & (down > 0), down, 0.0)
    tr = true_range(df)
    atr_ = tr.ewm(alpha=1.0 / period, adjust=False, min_periods=period).mean()
    plus_di = 100.0 * pd.Series(plus_dm, index=df.index).ewm(
        alpha=1.0 / period, adjust=False, min_periods=period
    ).mean() / atr_
    minus_di = 100.0 * pd.Series(minus_dm, index=df.index).ewm(
        alpha=1.0 / period, adjust=False, min_periods=period
    ).mean() / atr_
    dx = 100.0 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0.0, np.nan)
    return dx.ewm(alpha=1.0 / period, adjust=False, min_periods=period).mean()
