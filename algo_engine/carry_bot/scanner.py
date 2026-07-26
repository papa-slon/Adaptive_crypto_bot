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


def decide_rotation(held: list[str], ranked: list[Candidate], n_slots: int,
                    held_minutes: dict[str, float] | None = None,
                    exit_funding: float = 0.0, switch_edge: float = 1.4,
                    min_hold_minutes: float = 4320.0) -> tuple[list[str], list[Candidate]]:
    """Decide which slots to close and which candidates to open — PURE, so the
    live autopilot and the historical backtest run the identical policy.

    Rotation is expensive: closing one carry and opening another is four taker
    fills (~0.3% of notional). Measured over a year, rotating on every weekly
    re-rank costs more than the entire funding edge. So a held slot is only
    given up when:
      * its funding actually went bad (below `exit_funding`), or
      * a candidate is `switch_edge` times better AND the slot has been held at
        least `min_hold_minutes`.

    Returns (symbols_to_close, candidates_to_open).
    """
    held_minutes = held_minutes or {}
    by_symbol = {c.symbol: c for c in ranked}
    to_close: list[str] = []

    # 1) a coin that now PAYS us nothing (or charges us) is never worth holding
    for sym in held:
        cand = by_symbol.get(sym)
        if cand is not None and cand.mean_funding < exit_funding:
            to_close.append(sym)

    remaining = [s for s in held if s not in to_close]
    tradeable = [c for c in ranked if c.mean_funding >= exit_funding]
    to_open: list[Candidate] = []

    # 2) fill free capacity with the best payers we do not already hold
    for cand in tradeable:
        if len(remaining) + len(to_open) >= n_slots:
            break
        if cand.symbol not in remaining and cand.symbol not in {c.symbol for c in to_open}:
            to_open.append(cand)

    # 3) swap the weakest holding only for a decisively better payer
    if len(remaining) + len(to_open) >= n_slots and remaining:
        scored = [(s, by_symbol[s].score if s in by_symbol else 0.0) for s in remaining]
        worst_sym, worst_score = min(scored, key=lambda kv: kv[1])
        taken = set(remaining) | {c.symbol for c in to_open}
        best = next((c for c in tradeable if c.symbol not in taken), None)
        old_enough = held_minutes.get(worst_sym, 0.0) >= min_hold_minutes
        if best and old_enough and worst_score > 0 and best.score > worst_score * switch_edge:
            to_close.append(worst_sym)
            to_open.append(best)

    return to_close, to_open


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
