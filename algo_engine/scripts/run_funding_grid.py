"""Funding-aware adaptive grid sweep on REAL Binance data (klines + funding).

Compares three variants per symbol/timeframe:
  * base  — price-only grid (no funding accounting),
  * fund  — same grid, but real funding is credited/debited on open inventory,
  * tilt  — grid leans toward the funding-RECEIVING side to harvest carry.

Shows the funding contribution explicitly so we can see honestly whether real
funding pushes the ~flat grid into positive expectancy. OPTIMISTIC fills ->
confirm on DEMO. Run (needs internet -> GitHub runner).
"""
from __future__ import annotations

import statistics
import traceback

from algo_engine.backtest import bars_per_year_for
from algo_engine.data import (
    align_funding_to_bars,
    fetch_binance_vision_funding,
    fetch_binance_vision_klines,
)
from algo_engine.grid import GridConfig, simulate_grid

SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT", "DOGEUSDT"]
TFS = [(15, 6), (30, 8)]
MIN_POSITIVE_FRAC = 0.60


def main() -> int:
    print("# Funding-aware adaptive grid — REAL Binance klines + funding\n")
    print(f"symbols={SYMBOLS}  maker-ish fees  (OPTIMISTIC fills — confirm on DEMO)\n")
    data = {}
    for interval, months in TFS:
        for symbol in SYMBOLS:
            try:
                df = fetch_binance_vision_klines(symbol, interval, months=months)
                fnd = fetch_binance_vision_funding(symbol, months=months)
                data[(symbol, interval)] = (df, align_funding_to_bars(df.index, fnd))
            except Exception as exc:  # noqa: BLE001
                print(f"FETCH FAILED {symbol} {interval}m: {type(exc).__name__} {str(exc)[:40]}")
                traceback.print_exc()

    variants = {
        "base": (GridConfig(), None),
        "fund": (GridConfig(), "f"),
        "tilt": (GridConfig(funding_tilt=True, tilt_levels=2), "f"),
    }
    agg = {}  # (variant, interval) -> list[(ret, killed)]
    print("| variant | symbol | tf | ret% | funding% | maxDD% | killed |")
    print("|---|---|---|---|---|---|---|")
    for vname, (cfg, usef) in variants.items():
        for (symbol, interval), (df, fbar) in data.items():
            try:
                r = simulate_grid(df, cfg, bars_per_year=bars_per_year_for(interval),
                                  funding_per_bar=(fbar if usef else None))
            except Exception as exc:  # noqa: BLE001
                print(f"| {vname} | {symbol} | {interval}m | RUN FAILED {str(exc)[:25]} |||")
                continue
            print(f"| {vname} | {symbol} | {interval}m | {r['total_return']*100:+.1f} | "
                  f"{r['funding_return']*100:+.1f} | {r['max_drawdown']*100:.1f} | "
                  f"{'yes' if r['killed'] else ''} |")
            agg.setdefault((vname, interval), []).append((r["total_return"], r["killed"]))

    print("\n## Robustness (across symbols)\n")
    print("| variant | tf | symbols+ | median ret% | killed | PASS |")
    print("|---|---|---|---|---|---|")
    winners = []
    for (vname, interval), rows in sorted(agg.items()):
        rets = [x[0] for x in rows]
        pos = sum(1 for x in rets if x > 0)
        nkill = sum(1 for x in rows if x[1])
        med = statistics.median(rets)
        passed = (pos / len(rets) >= MIN_POSITIVE_FRAC) and (med > 0) and (nkill <= len(rows) // 3)
        if passed:
            winners.append((vname, interval, med, pos / len(rets)))
        print(f"| {vname} | {interval}m | {pos}/{len(rets)} | {med*100:+.1f} | "
              f"{nkill}/{len(rows)} | {'YES' if passed else 'no'} |")

    print("\n## Verdict\n")
    if winners:
        print("Funding-aware grid configs that generalize (OPTIMISTIC — DEMO next):")
        for vname, interval, med, pos in sorted(winners, key=lambda w: -w[2]):
            print(f"  - **{vname} @ {interval}m** — median ret {med*100:+.1f}%, "
                  f"positive on {pos*100:.0f}% of symbols")
    else:
        print("No variant cleared the gate. Compare the 'funding%' column vs 'base'")
        print("ret to see how much funding adds — and whether the tilt's directional")
        print("risk (short into positive funding = short into the rally) cancels it.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
