"""Portfolio carry backtest: does a SCANNER that rotates coins by funding beat
sitting in BTC — and what does it actually yield on the capital it ties up?

Method (walk-forward, no look-ahead):
  * universe = liquid USDT perps with Binance Vision funding history,
  * every REBALANCE_DAYS, rank symbols using ONLY funding observed in the
    trailing LOOKBACK_DAYS (the same `rank_candidates` the live bot uses),
  * hold an equal-weight delta-neutral carry on the top K,
  * collect each slot's realised funding over the next period,
  * charge round-trip taker fees on both legs of every slot that CHANGES.

Capital accounting is the honest one: a carry slot ties up the spot notional
PLUS the perp margin (notional / leverage). Yield is reported on that total,
which is why these numbers are lower than a naive "funding / spot notional".

Price risk is delta-neutral by construction, so P&L is funding minus costs;
basis drift is excluded (measured at ~0 over these windows) and fills are
assumed — treat the result as an upper bound to confirm on demo.
"""
from __future__ import annotations

import statistics
import traceback
from collections import defaultdict

from algo_engine.carry_bot.scanner import (
    annualise,
    decide_rotation,
    rank_candidates,
    stats_from_series,
)
from algo_engine.data import fetch_binance_vision_funding

UNIVERSE = [
    "BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT", "DOGEUSDT",
    "ADAUSDT", "AVAXUSDT", "LINKUSDT", "DOTUSDT", "LTCUSDT", "TRXUSDT",
    "NEARUSDT", "APTUSDT", "ARBUSDT", "OPUSDT", "SUIUSDT", "FILUSDT",
]
MONTHS = 12
LOOKBACK_DAYS = 14        # trailing window the scanner ranks on
REBALANCE_DAYS = 7        # how often the scanner re-picks
TOP_K = 3                 # simultaneous carry slots
# Rotation policy — identical to the live autopilot's defaults
EXIT_FUNDING = 0.0        # drop a coin that stops paying us
SWITCH_EDGE = 1.4         # a replacement must be this much better
MIN_HOLD_MINUTES = 4320.0 # 3 days: a round trip costs ~0.3% of notional
LEVERAGE = 1.0            # perp leg leverage (capital = notional * (1 + 1/L))
FEE_PER_LEG = 0.00055     # taker, per side
SLIP_PER_LEG = 0.0002
SETTLEMENTS_PER_DAY = 3


def capital_multiplier(leverage: float) -> float:
    """Capital tied up per 1 unit of carry notional: spot leg + perp margin."""
    return 1.0 + 1.0 / max(leverage, 1e-9)


def load_universe(months: int) -> dict[str, list]:
    series: dict[str, list] = {}
    for sym in UNIVERSE:
        try:
            s = fetch_binance_vision_funding(sym, months=months)
            if len(s) > 50:
                series[sym] = [(ts, float(v)) for ts, v in s.items()]
        except Exception as exc:  # noqa: BLE001 — a missing archive must not stop the sweep
            print(f"  skip {sym}: {type(exc).__name__} {str(exc)[:60]}")
    return series


def simulate(series: dict[str, list], top_k: int, leverage: float,
             rebalance_days: int, lookback_days: int, rotate: bool = True) -> dict:
    """Walk forward over the funding timeline; return equity + diagnostics."""
    # unified, sorted timeline of every settlement across the universe
    per_symbol = {s: dict(rows) for s, rows in series.items()}
    all_ts = sorted({ts for rows in series.values() for ts, _ in rows})
    if not all_ts:
        return {}

    cap_mult = capital_multiplier(leverage)
    switch_cost = 2 * (FEE_PER_LEG + SLIP_PER_LEG) * 2   # open+close, two legs
    equity = 1.0
    peak = 1.0
    max_dd = 0.0
    held: list[str] = []
    opened_at: dict[str, int] = {}
    switches = 0
    curve = []
    picks_log: dict[str, int] = defaultdict(int)

    lookback = lookback_days * SETTLEMENTS_PER_DAY
    step = rebalance_days * SETTLEMENTS_PER_DAY
    history: dict[str, list[float]] = defaultdict(list)

    for i, ts in enumerate(all_ts):
        # 1) accrue this settlement for the slots we already hold
        if held:
            slot_capital = equity / len(held)
            # notional per slot = slot capital / cap_mult (the rest is margin)
            for sym in held:
                rate = per_symbol.get(sym, {}).get(ts)
                if rate is None:
                    continue
                equity += (slot_capital / cap_mult) * float(rate)

        # 2) record history for the ranker (only what has already happened)
        for sym, rows in per_symbol.items():
            r = rows.get(ts)
            if r is not None:
                history[sym].append(float(r))

        # 3) periodically re-rank, applying the SAME policy the live bot uses
        if rotate and i >= lookback and i % step == 0:
            stats = {s: stats_from_series(h[-lookback:]) for s, h in history.items()
                     if len(h) >= lookback}
            ranked = rank_candidates(stats, top_n=max(top_k * 3, 6), min_obs=lookback // 2)
            held_minutes = {s: (i - opened_at.get(s, i)) * 8 * 60 for s in held}
            to_close, to_open = decide_rotation(
                held=held, ranked=ranked, n_slots=top_k, held_minutes=held_minutes,
                exit_funding=EXIT_FUNDING, switch_edge=SWITCH_EDGE,
                min_hold_minutes=MIN_HOLD_MINUTES)
            # each closed or opened slot pays its share of the round trip
            moves = len(to_close) + len(to_open)
            if moves:
                equity -= equity * (moves / (2.0 * max(top_k, 1))) * switch_cost / cap_mult
                switches += moves
            for sym in to_close:
                held.remove(sym); opened_at.pop(sym, None)
            for c in to_open:
                held.append(c.symbol); opened_at[c.symbol] = i; picks_log[c.symbol] += 1
        elif not rotate and not held and i >= lookback:
            held = [UNIVERSE[0]]          # BTC-only baseline
            equity -= equity * switch_cost / cap_mult

        peak = max(peak, equity)
        if peak > 0:
            max_dd = max(max_dd, (peak - equity) / peak)
        curve.append(equity)

    years = len(all_ts) / (SETTLEMENTS_PER_DAY * 365.0)
    total = equity - 1.0
    ann = ((1 + total) ** (1 / years) - 1) if years > 0 and total > -1 else 0.0
    return {"total_return": total, "annualized": ann, "max_drawdown": max_dd,
            "switches": switches, "years": years, "curve": curve,
            "most_picked": sorted(picks_log.items(), key=lambda kv: -kv[1])[:8]}


def main() -> int:
    print("# Portfolio carry with a funding SCANNER — real Binance funding history\n")
    print(f"universe={len(UNIVERSE)} symbols  months={MONTHS}  top_k={TOP_K}  "
          f"lookback={LOOKBACK_DAYS}d  rebalance={REBALANCE_DAYS}d  leverage={LEVERAGE}x")
    print(f"capital per slot = notional x {capital_multiplier(LEVERAGE):.2f} "
          f"(spot leg + perp margin) — yields are on TOTAL capital\n")

    series = load_universe(MONTHS)
    if not series:
        print("no funding data fetched (network blocked?)")
        return 0
    print(f"loaded funding history for {len(series)} symbols\n")

    # what the market paid, per symbol, over the whole window
    print("## Funding actually paid per symbol (whole window)\n")
    print("| symbol | settlements | mean per 8h | naive annualised |")
    print("|---|---|---|---|")
    rows = []
    for sym, data in series.items():
        st = stats_from_series([v for _, v in data])
        rows.append((sym, st))
    for sym, st in sorted(rows, key=lambda r: -r[1]["mean"]):
        print(f"| {sym} | {st['n']} | {st['mean']*100:+.4f}% | {annualise(st['mean']):+.1f}% |")

    print("\n## Strategy comparison\n")
    print("| strategy | ann. yield on capital | total | maxDD | switches |")
    print("|---|---|---|---|---|")
    scanner = simulate(series, TOP_K, LEVERAGE, REBALANCE_DAYS, LOOKBACK_DAYS, rotate=True)
    btc = simulate({k: v for k, v in series.items() if k == "BTCUSDT"},
                   1, LEVERAGE, REBALANCE_DAYS, LOOKBACK_DAYS, rotate=False)
    for label, r in (("scanner (top-%d, rotating)" % TOP_K, scanner), ("BTC-only (hold)", btc)):
        if not r:
            continue
        print(f"| {label} | **{r['annualized']*100:+.2f}%** | {r['total_return']*100:+.2f}% | "
              f"{r['max_drawdown']*100:.2f}% | {r['switches']} |")

    if scanner.get("most_picked"):
        print("\nMost-picked coins by the scanner: " +
              ", ".join(f"{s} ({n}x)" for s, n in scanner["most_picked"]))

    print("\n## Sensitivity — how many slots and how much leverage\n")
    print("| top_k | leverage | ann. yield on capital | maxDD |")
    print("|---|---|---|---|")
    for k in (1, 2, 3, 5):
        for lev in (1.0, 2.0, 3.0):
            r = simulate(series, k, lev, REBALANCE_DAYS, LOOKBACK_DAYS, rotate=True)
            if r:
                print(f"| {k} | {lev:g}x | {r['annualized']*100:+.2f}% | {r['max_drawdown']*100:.2f}% |")

    print("\n## Honest reading\n")
    print("- Yield is on capital ACTUALLY tied up (spot notional + perp margin), not on the")
    print("  spot leg alone — that is why it is lower than a naive funding sum.")
    print("- Delta-neutral means price risk is hedged, so drawdown here comes from negative")
    print("  funding regimes and switching costs, not from the market direction.")
    print("- Excluded: basis drift (measured ~0), fill slippage beyond the modelled taker cost,")
    print("  and exchange minimum sizes. Confirm on demo before sizing up.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
