import numpy as np
import pandas as pd

from algo_engine import indicators as ind
from algo_engine.data import synthetic_ohlcv


def test_ema_constant_series_is_constant():
    s = pd.Series([100.0] * 50)
    out = ind.ema(s, 10).dropna()
    assert np.allclose(out, 100.0)


def test_atr_is_positive_and_finite():
    df = synthetic_ohlcv(n=500, seed=1)
    a = ind.atr(df, 14).dropna()
    assert (a > 0).all()
    assert np.isfinite(a).all()


def test_rolling_zscore_centered():
    df = synthetic_ohlcv(n=2000, seed=2)
    z = ind.rolling_zscore(df["close"] - ind.ema(df["close"], 20), 200).dropna()
    # mean of a rolling z-score over many windows should sit near zero
    assert abs(z.mean()) < 0.5
    assert np.isfinite(z).all()


def test_donchian_no_lookahead():
    df = synthetic_ohlcv(n=300, seed=3)
    upper, lower = ind.donchian(df, 20)
    # level at bar i must be built from bars strictly before i (shifted)
    raw_upper = df["high"].rolling(20).max()
    assert upper.iloc[50] == raw_upper.iloc[49]


def test_rsi_bounds():
    df = synthetic_ohlcv(n=1000, seed=4)
    r = ind.rsi(df["close"], 14).dropna()
    assert (r >= 0).all() and (r <= 100).all()
