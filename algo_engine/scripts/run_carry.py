"""Delta-neutral funding carry sweep on REAL data: spot + perp + funding.

For each symbol: long spot / short perp (1x, delta-neutral), collect funding.
Reports ANNUALIZED yield, the funding vs basis split, and drawdown. This is the
honest positive-expectancy construct — modest yield, low risk.

Run (needs internet -> GitHub runner):  python -m algo_engine.scripts.run_carry
"""
from __future__ import annotations

import statistics
import traceback

from algo_engine.backtest import bars_per_year_for
from algo_engine.carry import CarryConfig, simulate_carry
from algo_engine.data import (
    align_funding_to_bars,
    fetch_binance_vision_funding,
    fetch_binance_vision_klines,
)

SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT", "DOGEUSDT"]
INTERVAL = 60
MONTHS = 8


def load(symbol):
    spot = fetch_binance_vision_klines(symbol, INTERVAL, months=MONTHS, market="spot")["close"]
    perp = fetch_binance_vision_klines(symbol, INTERVAL, months=MONTHS, market="futures/um")["close"]
    idx = spot.index.intersection(perp.index)
    spot, perp = spot.reindex(idx).dropna(), perp.reindex(idx).dropna()
    idx = spot.index.intersection(perp.index)
    spot, perp = spot.reindex(idx), perp.reindex(idx)
    fnd = fetch_binance_vision_funding(symbol, months=MONTHS)
    return spot, perp, align_funding_to_bars(spot.index, fnd)


def main() -> int:
    bpy = bars_per_year_for(INTERVAL)
    print("# Delta-neutral funding carry — REAL spot + perp + funding (1h, ~8mo)\n")
    print(f"symbols={SYMBOLS}  long spot / short perp, 1x  (taker fees both legs)\n")
    print("| mode | symbol | ann.yield% | total% | funding% | basis% | maxDD% | toggles |")
    print("|---|---|---|---|---|---|---|---|")
    agg = {"static": [], "timed": []}
    for symbol in SYMBOLS:
        try:
            spot, perp, fbar = load(symbol)
        except Exception as exc:  # noqa: BLE001
            print(f"| — | {symbol} | FETCH FAILED: {type(exc).__name__} {str(exc)[:40]} ||||||")
            traceback.print_exc()
            continue
        for mode, cfg in (("static", CarryConfig()), ("timed", CarryConfig(timed=True))):
            r = simulate_carry(spot, perp, fbar, cfg, bpy)
            print(f"| {mode} | {symbol} | {r['annualized']*100:+.1f} | {r['total_return']*100:+.1f} | "
                  f"{r['funding_total']*100:+.1f} | {r['basis_total']*100:+.1f} | "
                  f"{r['max_drawdown']*100:.1f} | {r['toggles']} |")
            agg[mode].append((symbol, r))

    print("\n## Robustness (across symbols)\n")
    print("| mode | symbols+ | median ann.yield% | median maxDD% |")
    print("|---|---|---|---|")
    best = []
    for mode, rows in agg.items():
        if not rows:
            continue
        anns = [r["annualized"] for _, r in rows]
        dds = [r["max_drawdown"] for _, r in rows]
        pos = sum(1 for a in anns if a > 0)
        med = statistics.median(anns)
        print(f"| {mode} | {pos}/{len(rows)} | {med*100:+.1f} | {statistics.median(dds)*100:.1f} |")
        if pos / len(rows) >= 0.6 and med > 0:
            best.append((mode, med, pos / len(rows)))

    print("\n## Verdict\n")
    if best:
        for mode, med, pos in sorted(best, key=lambda b: -b[1]):
            print(f"  - **{mode} carry** — median annualized {med*100:+.1f}%, "
                  f"positive on {pos*100:.0f}% of symbols.")
        print("\nThis is REAL positive expectancy at low risk (delta-neutral). Yields")
        print("are modest by design. Next: DEMO both legs, watch perp margin + the")
        print("8h funding settlement, then size up gradually. Leverage on the perp")
        print("margin can amplify yield — and risk — separately.")
    else:
        print("Carry did not show positive median yield over this window — funding")
        print("was net too low / negative after both legs' fees. Honest: even carry")
        print("isn't free money in every regime.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
