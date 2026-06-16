"""Sanity tests for the delta-neutral cash-and-carry simulator."""
from __future__ import annotations

import numpy as np
import pandas as pd

from algo_engine.carry import CarryConfig, simulate_carry

BPY = 8760.0  # 1h bars per year


def _series(arr):
    idx = pd.date_range("2025-01-01", periods=len(arr), freq="1h", tz="UTC")
    return pd.Series(arr, index=idx)


def test_carry_collects_positive_funding_delta_neutral():
    # spot == perp, both flat -> zero price/basis pnl; positive funding every 8h
    n = 24 * 30
    spot = _series(np.full(n, 100.0))
    perp = _series(np.full(n, 100.0))
    fb = np.zeros(n)
    fb[::8] = 0.0001                       # +0.01%/8h funding
    r = simulate_carry(spot, perp, fb, CarryConfig(fee=0.0, slippage=0.0), BPY)
    assert r["funding_total"] > 0, r
    assert abs(r["basis_total"]) < 1e-9, r  # delta-neutral: no price pnl
    assert r["total_return"] > 0, r


def test_carry_price_neutral_when_spot_and_perp_move_together():
    # both rally +50% identically -> net price pnl ~0 (long spot offsets short perp)
    n = 200
    path = np.linspace(100.0, 150.0, n)
    r = simulate_carry(_series(path), _series(path), np.zeros(n),
                       CarryConfig(fee=0.0, slippage=0.0), BPY)
    assert abs(r["total_return"]) < 1e-6, r


def test_timed_carry_skips_negative_funding():
    # negative funding throughout -> timed mode should stay flat (never pay)
    n = 24 * 20
    spot = _series(np.full(n, 100.0)); perp = _series(np.full(n, 100.0))
    fb = np.zeros(n); fb[::8] = -0.0002
    r = simulate_carry(spot, perp, fb, CarryConfig(fee=0.0004, timed=True), BPY)
    assert r["funding_total"] == 0.0, r     # never entered -> collected nothing
    assert r["toggles"] == 0, r
