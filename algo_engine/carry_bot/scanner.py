"""Funding scanner: pick which coins to carry, so the operator never has to.

The carry earns the funding the market pays. Funding differs hugely per coin
and changes over time, so a fixed symbol is a bad idea — this module ranks the
universe and selects the best few.

The SAME ranking function (`rank_candidates`) is used by the live bot and by
the historical portfolio backtest, so what we measure is what we trade.

Selection rules (deliberately conservative):
  * only coins whose TRAILING MEAN funding is positive — we are short the perp,
    so we need longs to be paying us, and one spike is not an edge,
  * require a minimum number of observed settlements (no thin history),
  * penalise volatile funding (mean / (1 + std)) so a stable 0.01% beats a
    lottery ticket that averaged the same via one outlier,
  * drop coins whose exchange minimum order size does not fit the per-slot
    capital, and coins below a liquidity floor.
"""
from __future__ import annotations

import json
import urllib.request
from dataclasses import dataclass, field


@dataclass
class Candidate:
    symbol: str
    mean_funding: float          # per 8h settlement, fraction
    std_funding: float
    n_obs: int
    score: float = 0.0
    ann_pct: float = 0.0         # naive annualised carry, % (3 settlements/day)
    extra: dict = field(default_factory=dict)


def annualise(funding_per_8h: float) -> float:
    """Funding is paid ~3x/day; express it as a simple annual percentage."""
    return funding_per_8h * 3.0 * 365.0 * 100.0


def rank_candidates(stats: dict[str, dict], top_n: int = 3, min_obs: int = 20,
                    min_mean_funding: float = 0.00002,
                    max_rel_std: float = 3.0) -> list[Candidate]:
    """Rank symbols by risk-adjusted trailing funding.

    `stats` maps symbol -> {"mean": float, "std": float, "n": int, ...extra}.
    Returns the best `top_n` candidates that clear the filters, best first.

    `max_rel_std` hard-rejects lottery tickets: a coin whose funding standard
    deviation exceeds this multiple of its mean averaged well only because of a
    spike, and a spike is not income we can rely on. Without this a thin slate
    could still hand a slot to such a coin just to fill it.
    """
    out: list[Candidate] = []
    for sym, s in stats.items():
        n = int(s.get("n", 0))
        mean = float(s.get("mean", 0.0))
        std = float(s.get("std", 0.0))
        if n < min_obs or mean < min_mean_funding:
            continue
        if mean > 0 and (std / mean) > max_rel_std:
            continue
        # stability-weighted: a steady payer outranks a spiky one with equal mean
        score = mean / (1.0 + (std / abs(mean) if mean else 0.0))
        out.append(Candidate(symbol=sym, mean_funding=mean, std_funding=std, n_obs=n,
                             score=score, ann_pct=annualise(mean),
                             extra={k: v for k, v in s.items() if k not in ("mean", "std", "n")}))
    out.sort(key=lambda c: -c.score)
    return out[:top_n]


def stats_from_series(rates: list[float]) -> dict:
    """Mean/std/count for a list of funding settlements (no numpy needed)."""
    n = len(rates)
    if n == 0:
        return {"mean": 0.0, "std": 0.0, "n": 0}
    mean = sum(rates) / n
    var = sum((r - mean) ** 2 for r in rates) / n if n > 1 else 0.0
    return {"mean": mean, "std": var ** 0.5, "n": n}


# ---------------------------------------------------------------- live scan
_BYBIT_TICKERS = "https://api.bybit.com/v5/market/tickers?category=linear"
_BYBIT_TICKERS_DEMO = "https://api-demo.bybit.com/v5/market/tickers?category=linear"


def scan_bybit_live(top_n: int = 3, min_turnover_usdt: float = 20_000_000.0,
                    url: str = _BYBIT_TICKERS, timeout: int = 20) -> list[Candidate]:
    """One-shot live scan of Bybit USDT perps by CURRENT funding rate.

    This is the instantaneous view (one settlement), so it is only used to
    refresh an existing ranking, never as the sole reason to enter — the live
    runner blends it with the trailing history from `rank_candidates`.
    """
    with urllib.request.urlopen(url, timeout=timeout) as resp:  # noqa: S310
        payload = json.loads(resp.read().decode())
    if payload.get("retCode") not in (0, None):
        raise RuntimeError(f"Bybit tickers error: {payload.get('retMsg')}")
    stats: dict[str, dict] = {}
    for row in payload.get("result", {}).get("list", []):
        sym = row.get("symbol", "")
        if not sym.endswith("USDT"):
            continue
        try:
            rate = float(row.get("fundingRate") or 0.0)
            turnover = float(row.get("turnover24h") or 0.0)
        except (TypeError, ValueError):
            continue
        if turnover < min_turnover_usdt:
            continue
        # a single observation: n=1 would be filtered out, so mark it explicitly
        stats[sym] = {"mean": rate, "std": 0.0, "n": 1, "turnover24h": turnover,
                      "price": float(row.get("lastPrice") or 0.0)}
    return rank_candidates(stats, top_n=top_n, min_obs=1)
