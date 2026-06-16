"""Adaptive-grid sweep on REAL Binance data (15m + 30m), multi-symbol, with a
robustness gate. Grid backtests are mildly OPTIMISTIC (OHLC fill approximation,
exact-rung fills, no queue), so treat a pass as an upper bound to be confirmed
on DEMO — not a green light to go live.

Run (needs internet -> GitHub runner):  python -m algo_engine.scripts.run_grid
"""
from __future__ import annotations

import statistics
import traceback

from algo_engine.backtest import bars_per_year_for
from algo_engine.data import fetch_binance_vision_klines
from algo_engine.grid import GridConfig, simulate_grid

SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT", "DOGEUSDT"]
TFS = [(15, 6), (30, 8)]   # (interval_minutes, months)

# a few sensible configs (NOT a fitted search) — vary spacing + trend gate only
CONFIGS = {
    "grid_tight":  GridConfig(step_atr=0.5, n_levels=6, trend_block=1.0),
    "grid_wide":   GridConfig(step_atr=1.0, n_levels=5, trend_block=1.2),
    "grid_notrend": GridConfig(step_atr=0.6, n_levels=6, trend_block=99.0),  # gate OFF (baseline)
}

MIN_POSITIVE_FRAC = 0.60
MIN_MEDIAN_RET = 0.0


def main() -> int:
    cache = {}
    print("# Adaptive grid sweep — REAL Binance data (15m/30m)\n")
    print(f"symbols={SYMBOLS}  maker-ish fees  (results are an OPTIMISTIC upper bound)\n")
    for interval, months in TFS:
        for symbol in SYMBOLS:
            try:
                cache[(symbol, interval)] = fetch_binance_vision_klines(symbol, interval, months=months)
            except Exception as exc:  # noqa: BLE001
                print(f"FETCH FAILED {symbol} {interval}m: {type(exc).__name__} {str(exc)[:40]}")
                traceback.print_exc()

    agg = {}  # (config, interval) -> list[(symbol, ret, killed)]
    print("| config | symbol | tf | fills | closed | win% | PF | ret% | maxDD% | killed |")
    print("|---|---|---|---|---|---|---|---|---|---|")
    for cname, cfg in CONFIGS.items():
        for (symbol, interval), df in cache.items():
            try:
                r = simulate_grid(df, cfg, bars_per_year=bars_per_year_for(interval))
            except Exception as exc:  # noqa: BLE001
                print(f"| {cname} | {symbol} | {interval}m | RUN FAILED {str(exc)[:30]} |||||||")
                continue
            pf = r["profit_factor"]
            pf_s = "inf" if pf == float("inf") else f"{pf:.2f}"
            print(
                f"| {cname} | {symbol} | {interval}m | {r['n_fills']} | {r['n_closed']} | "
                f"{r['win_rate']*100:.0f} | {pf_s} | {r['total_return']*100:+.1f} | "
                f"{r['max_drawdown']*100:.1f} | {'yes' if r['killed'] else ''} |"
            )
            agg.setdefault((cname, interval), []).append((symbol, r["total_return"], r["killed"]))

    print("\n## Robustness (across symbols)\n")
    print("| config | tf | symbols+ | median ret% | killed | PASS |")
    print("|---|---|---|---|---|---|")
    winners = []
    for (cname, interval), rows in sorted(agg.items()):
        rets = [x[1] for x in rows]
        pos = sum(1 for x in rets if x > 0)
        nkill = sum(1 for x in rows if x[2])
        med = statistics.median(rets)
        passed = (pos / len(rets) >= MIN_POSITIVE_FRAC) and (med > MIN_MEDIAN_RET) and (nkill <= len(rows) // 3)
        if passed:
            winners.append((cname, interval, med, pos / len(rets)))
        print(f"| {cname} | {interval}m | {pos}/{len(rets)} | {med*100:+.1f} | {nkill}/{len(rows)} | "
              f"{'YES' if passed else 'no'} |")

    print("\n## Verdict\n")
    if winners:
        print("Grid configs that generalize across symbols (OPTIMISTIC — confirm on DEMO):")
        for cname, interval, med, pos in sorted(winners, key=lambda w: -w[2]):
            print(f"  - **{cname} @ {interval}m** — median ret {med*100:+.1f}%, positive on {pos*100:.0f}% of symbols")
        print("\nGrid caveat: a backtest can look good for months and then a single")
        print("strong trend unwinds accumulated inventory. The trend gate + kill-switch")
        print("limit that, but DEMO validation across a trend is mandatory before live.")
    else:
        print("No grid config cleared the robustness gate on 15m/30m even with optimistic fills.")
        print("Honest read: adaptive grid does not show a generalizing edge here either.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
