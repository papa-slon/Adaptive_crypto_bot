"""Market data: real Bybit klines (public, no API key) + local cache, plus a
synthetic OHLCV generator for offline tests and dry runs.

DataFrame contract everywhere in algo_engine:
    index   : tz-aware UTC DatetimeIndex, ascending
    columns : open, high, low, close, volume  (float)
"""
from __future__ import annotations

import json
import time
import urllib.parse
import urllib.request
from pathlib import Path

import numpy as np
import pandas as pd

# Bybit interval strings keyed by minutes (their API uses these literals).
_INTERVAL_MAP = {1: "1", 3: "3", 5: "5", 15: "15", 30: "30", 60: "60", 240: "240"}
_PUBLIC_BASE = "https://api.bybit.com"  # public market data (same for demo accts)


def _normalize(df: pd.DataFrame) -> pd.DataFrame:
    df = df[["open", "high", "low", "close", "volume"]].astype(float)
    df = df[~df.index.duplicated(keep="last")].sort_index()
    return df


# --------------------------------------------------------------------------- #
# Real data
# --------------------------------------------------------------------------- #
def fetch_bybit_klines(
    symbol: str,
    interval_min: int,
    days: float = 30.0,
    category: str = "linear",
    base_url: str = _PUBLIC_BASE,
    sleep: float = 0.15,
) -> pd.DataFrame:
    """Download the last `days` of klines from Bybit public REST (paginated).

    No authentication required. Runs only when YOU call it.
    """
    if interval_min not in _INTERVAL_MAP:
        raise ValueError(f"unsupported interval {interval_min}m; use {sorted(_INTERVAL_MAP)}")
    interval = _INTERVAL_MAP[interval_min]
    end_ms = int(time.time() * 1000)
    start_ms = end_ms - int(days * 24 * 60 * 60 * 1000)

    rows: list[list] = []
    cursor = end_ms
    while cursor > start_ms:
        params = {
            "category": category,
            "symbol": symbol,
            "interval": interval,
            "end": cursor,
            "limit": 1000,
        }
        url = f"{base_url}/v5/market/kline?" + urllib.parse.urlencode(params)
        with urllib.request.urlopen(url, timeout=20) as resp:  # noqa: S310 (trusted host)
            payload = json.loads(resp.read().decode())
        if payload.get("retCode") != 0:
            raise RuntimeError(f"Bybit error: {payload.get('retMsg')} ({payload.get('retCode')})")
        batch = payload["result"]["list"]  # newest-first
        if not batch:
            break
        rows.extend(batch)
        oldest = int(batch[-1][0])
        if oldest <= start_ms or len(batch) < 1000:
            break
        cursor = oldest - 1
        time.sleep(sleep)  # be polite to the public endpoint

    if not rows:
        raise RuntimeError("no klines returned")

    df = pd.DataFrame(
        rows, columns=["ts", "open", "high", "low", "close", "volume", "turnover"]
    )
    df["ts"] = pd.to_datetime(df["ts"].astype("int64"), unit="ms", utc=True)
    df = df.set_index("ts")
    df = df[df.index >= pd.to_datetime(start_ms, unit="ms", utc=True)]
    return _normalize(df)


def load(
    symbol: str,
    interval_min: int,
    days: float = 30.0,
    cache_dir: str | Path = "data_cache",
    refresh: bool = False,
) -> pd.DataFrame:
    """Fetch with a local CSV cache. Pass refresh=True to force re-download."""
    cache_dir = Path(cache_dir)
    cache_dir.mkdir(parents=True, exist_ok=True)
    path = cache_dir / f"{symbol}_{interval_min}m_{int(days)}d.csv"
    if path.exists() and not refresh:
        return from_csv(path)
    df = fetch_bybit_klines(symbol, interval_min, days)
    to_csv(df, path)
    return df


def to_csv(df: pd.DataFrame, path: str | Path) -> None:
    df.to_csv(path, index_label="ts")


def from_csv(path: str | Path) -> pd.DataFrame:
    df = pd.read_csv(path, parse_dates=["ts"]).set_index("ts")
    if df.index.tz is None:
        df.index = df.index.tz_localize("UTC")
    return _normalize(df)


# --------------------------------------------------------------------------- #
# Synthetic data (offline tests / dry runs — never hits the network)
# --------------------------------------------------------------------------- #
def synthetic_ohlcv(
    n: int = 5000,
    start_price: float = 30_000.0,
    interval_min: int = 5,
    vol: float = 0.0025,
    drift: float = 0.0,
    seed: int = 7,
    trend_strength: float = 0.0,
) -> pd.DataFrame:
    """Geometric-random-walk OHLCV with volatility clustering.

    `trend_strength` adds gentle autocorrelation so trend strategies have
    something to chew on. This is for MECHANICS testing only — never read a
    backtest on synthetic data as evidence of real edge.
    """
    rng = np.random.default_rng(seed)
    shocks = rng.normal(drift, vol, size=n)
    # simple AR(1) momentum to create trends/ranges
    momentum = np.zeros(n)
    for t in range(1, n):
        momentum[t] = trend_strength * momentum[t - 1] + shocks[t]
    log_ret = momentum
    close = start_price * np.exp(np.cumsum(log_ret))

    open_ = np.empty(n)
    open_[0] = start_price
    open_[1:] = close[:-1]
    intrabar = np.abs(rng.normal(0, vol, size=n)) * close
    high = np.maximum(open_, close) + intrabar
    low = np.minimum(open_, close) - intrabar
    volume = rng.uniform(100, 1000, size=n)

    idx = pd.date_range(
        end=pd.Timestamp.now("UTC").floor("min"),
        periods=n,
        freq=f"{interval_min}min",
        tz="UTC",
    )
    return pd.DataFrame(
        {"open": open_, "high": high, "low": low, "close": close, "volume": volume},
        index=idx,
    )
