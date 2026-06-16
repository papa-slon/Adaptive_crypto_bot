"""Sanity tests for the adaptive grid simulator.

These prove the simulator behaves as a grid SHOULD:
  * ranging market  -> harvests oscillation (positive, many fills, not killed),
  * strong trend    -> trend gate protects it (no catastrophic blow-up).
A simulator that fails these would make any real-data result meaningless.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from algo_engine.data import align_funding_to_bars
from algo_engine.grid import GridConfig, simulate_grid


def _ohlc_from_path(path: np.ndarray, wick: float) -> pd.DataFrame:
    idx = pd.date_range("2025-01-01", periods=len(path), freq="15min", tz="UTC")
    close = pd.Series(path, index=idx)
    open_ = close.shift(1).fillna(close.iloc[0])
    high = np.maximum(open_, close) + wick
    low = np.minimum(open_, close) - wick
    vol = pd.Series(1000.0, index=idx)
    return pd.DataFrame({"open": open_, "high": high, "low": low, "close": close, "volume": vol})


def test_grid_profits_in_a_range():
    t = np.arange(3000)
    path = 100.0 + 6.0 * np.sin(t / 12.0)        # clean oscillation, no trend
    df = _ohlc_from_path(path, wick=0.4)
    r = simulate_grid(df, GridConfig(step_atr=0.5, trend_block=99.0))  # gate off in a pure range
    assert r["n_fills"] > 20, r
    assert r["total_return"] > 0, r              # a grid must monetise oscillation
    assert not r["killed"], r


def test_grid_survives_strong_uptrend():
    t = np.arange(3000)
    path = 100.0 * (1.0 + 0.0006) ** t           # ~+0.06%/bar relentless uptrend
    df = _ohlc_from_path(path, wick=0.2)
    r = simulate_grid(df, GridConfig())
    # trend gate blocks new shorts into the rip -> must not blow up to the kill floor
    assert r["total_return"] > -0.25, r


def test_grid_survives_strong_downtrend():
    t = np.arange(3000)
    path = 100.0 * (1.0 - 0.0006) ** t           # relentless downtrend
    df = _ohlc_from_path(path, wick=0.2)
    r = simulate_grid(df, GridConfig())
    # trend gate blocks buying the falling knife -> protected, not a -25% wipeout
    assert r["total_return"] > -0.25, r


def test_align_funding_to_bars_maps_events():
    idx = pd.date_range("2025-01-01", periods=100, freq="15min", tz="UTC")
    # one funding event at the 10th bar's timestamp
    funding = pd.Series([0.0001], index=[idx[10]])
    arr = align_funding_to_bars(idx, funding)
    assert arr[10] == 0.0001 and arr.sum() == 0.0001


def test_funding_accounting_long_pays_positive_funding():
    # steady decline -> longs fill and stay open (TP above never hit); with
    # POSITIVE funding, held longs PAY -> funding_return must be negative.
    path = np.linspace(100.0, 80.0, 500)
    df = _ohlc_from_path(path, wick=0.2)
    fund = np.full(len(df), 0.0002)                  # positive every bar
    r = simulate_grid(df, GridConfig(step_atr=0.4, trend_block=99.0), funding_per_bar=fund)
    assert r["funding_return"] < 0, r


def test_funding_accounting_short_receives_positive_funding():
    # steady incline -> shorts fill and stay open; with POSITIVE funding, held
    # shorts RECEIVE -> funding_return must be positive.
    path = np.linspace(100.0, 120.0, 500)
    df = _ohlc_from_path(path, wick=0.2)
    fund = np.full(len(df), 0.0002)
    r = simulate_grid(df, GridConfig(step_atr=0.4, trend_block=99.0), funding_per_bar=fund)
    assert r["funding_return"] > 0, r
