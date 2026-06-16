"""Market data: real Bybit klines (public, no API key) + local cache, plus a
synthetic OHLCV generator for offline tests and dry runs.

DataFrame contract everywhere in algo_engine:
    index   : tz-aware UTC DatetimeIndex, ascending
    columns : open, high, low, close, volume  (float)
"""
from __future__ import annotations

import io
import json
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

_VISION_BASE = "https://data.binance.vision"  # public historical dumps (CDN, no key)
_VISION_INTERVALS = {1: "1m", 3: "3m", 5: "5m", 15: "15m", 30: "30m", 60: "1h", 240: "4h"}

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


def _recent_months(n: int) -> list[str]:
    """Return the last `n` 'YYYY-MM' strings ending at the current month."""
    now = datetime.now(timezone.utc)
    months = []
    y, m = now.year, now.month
    for _ in range(n):
        months.append(f"{y:04d}-{m:02d}")
        m -= 1
        if m == 0:
            m = 12
            y -= 1
    return list(reversed(months))


def fetch_binance_vision_klines(
    symbol: str,
    interval_min: int,
    months: int = 4,
    market: str = "futures/um",
) -> pd.DataFrame:
    """Download monthly kline archives from data.binance.vision (CDN, no auth).

    Reachable from datacenter IPs where the live exchange APIs are geo-blocked.
    Skips months whose archive doesn't exist yet (e.g. the current month).
    """
    if interval_min not in _VISION_INTERVALS:
        raise ValueError(f"unsupported interval {interval_min}m; use {sorted(_VISION_INTERVALS)}")
    interval = _VISION_INTERVALS[interval_min]
    frames: list[pd.DataFrame] = []
    # try a couple extra months to tolerate the missing current month
    for ym in _recent_months(months + 1):
        url = f"{_VISION_BASE}/data/{market}/monthly/klines/{symbol}/{interval}/{symbol}-{interval}-{ym}.zip"
        try:
            with urllib.request.urlopen(url, timeout=30) as resp:  # noqa: S310
                blob = resp.read()
        except urllib.error.HTTPError as exc:
            if exc.code in (403, 404):
                continue  # month not published yet
            raise
        zf = zipfile.ZipFile(io.BytesIO(blob))
        name = zf.namelist()[0]
        df = pd.read_csv(io.BytesIO(zf.read(name)), header=None)
        # some recent archives ship a header row -> drop it
        if not str(df.iloc[0, 0]).replace(".", "", 1).lstrip("-").isdigit():
            df = df.iloc[1:].reset_index(drop=True)
        df = df.iloc[:, :6]
        df.columns = ["open_time", "open", "high", "low", "close", "volume"]
        frames.append(df)

    if not frames:
        raise RuntimeError(f"no Binance Vision archives found for {symbol} {interval}")

    out = pd.concat(frames, ignore_index=True)
    ot = out["open_time"].astype("int64")
    # tolerate ms vs µs timestamps
    unit = "us" if ot.iloc[0] > 1e14 else "ms"
    out.index = pd.to_datetime(ot, unit=unit, utc=True)
    out = out[["open", "high", "low", "close", "volume"]]
    return _normalize(out)


def fetch_binance_vision_funding(symbol: str, months: int = 6) -> pd.Series:
    """Download real funding-rate history from data.binance.vision.

    Returns a Series indexed by UTC funding timestamp, value = funding rate
    (fraction, per 8h interval). Longs pay shorts when the rate is positive.
    """
    frames: list[pd.DataFrame] = []
    for ym in _recent_months(months + 1):
        url = (f"{_VISION_BASE}/data/futures/um/monthly/fundingRate/"
               f"{symbol}/{symbol}-fundingRate-{ym}.zip")
        try:
            with urllib.request.urlopen(url, timeout=30) as resp:  # noqa: S310
                blob = resp.read()
        except urllib.error.HTTPError as exc:
            if exc.code in (403, 404):
                continue
            raise
        zf = zipfile.ZipFile(io.BytesIO(blob))
        df = pd.read_csv(io.BytesIO(zf.read(zf.namelist()[0])), header=0)
        frames.append(df)

    if not frames:
        raise RuntimeError(f"no Binance Vision funding archives for {symbol}")

    out = pd.concat(frames, ignore_index=True)
    cols = {c.lower(): c for c in out.columns}
    tcol = next((cols[c] for c in cols if "time" in c), out.columns[0])
    rcol = next((cols[c] for c in cols if "rate" in c), out.columns[-1])
    ts = out[tcol].astype("int64")
    unit = "us" if ts.iloc[0] > 1e14 else "ms"
    idx = pd.to_datetime(ts, unit=unit, utc=True)
    s = pd.Series(out[rcol].astype(float).values, index=idx).sort_index()
    return s[~s.index.duplicated(keep="last")]


def align_funding_to_bars(bar_index: pd.DatetimeIndex, funding: pd.Series) -> np.ndarray:
    """Map funding events onto bars: each event lands on the bar that contains
    it. Returns a per-bar array (0.0 where no funding event occurs)."""
    out = np.zeros(len(bar_index), dtype=float)
    if len(bar_index) < 2 or funding.empty:
        return out
    # bar i covers [bar_index[i], bar_index[i+1]); use searchsorted on the left edge
    pos = bar_index.searchsorted(funding.index, side="right") - 1
    for p, rate in zip(pos, funding.values):
        if 0 <= p < len(out):
            out[p] += float(rate)
    return out


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
