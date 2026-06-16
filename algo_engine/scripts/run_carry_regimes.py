"""Carry characterization: how does the delta-neutral carry yield change across
funding REGIMES (recent vs a past high-funding bull window) and LEVERAGE?

Static carry only (timed is a proven fee trap). Reports per-window/leverage the
median annualized yield, median drawdown, and how many symbols would have had
their isolated perp leg LIQUIDATED (cross-account risk that leverage creates
even though the position is delta-neutral). Run on the GitHub runner.
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
# (label, end_month, months)
WINDOWS = [
    ("recent ~8mo", None, 8),
    ("bull 2024H2->25 (high funding)", "2025-02", 7),
]
LEVERAGES = [1.0, 3.0, 5.0]


def load(symbol, months, end_month):
    spot = fetch_binance_vision_klines(symbol, INTERVAL, months=months,
                                       market="spot", end_month=end_month)["close"]
    perp = fetch_binance_vision_klines(symbol, INTERVAL, months=months,
                                       market="futures/um", end_month=end_month)["close"]
    idx = spot.index.intersection(perp.index)
    spot, perp = spot.reindex(idx), perp.reindex(idx)
    fnd = fetch_binance_vision_funding(symbol, months=months, end_month=end_month)
    return spot, perp, align_funding_to_bars(spot.index, fnd)


def main() -> int:
    bpy = bars_per_year_for(INTERVAL)
    print("# Carry across funding regimes & leverage — REAL spot+perp+funding (1h)\n")
    print(f"symbols={SYMBOLS}  static carry, long spot / short perp\n")
    print("| window | leverage | median ann.yield% | median maxDD% | liquidated |")
    print("|---|---|---|---|---|")
    for wlabel, end_month, months in WINDOWS:
        cache = {}
        for symbol in SYMBOLS:
            try:
                cache[symbol] = load(symbol, months, end_month)
            except Exception as exc:  # noqa: BLE001
                print(f"| {wlabel} | — | FETCH FAILED {symbol}: {str(exc)[:30]} |||")
                traceback.print_exc()
        for lev in LEVERAGES:
            anns, dds, liqs = [], [], 0
            for symbol, (spot, perp, fbar) in cache.items():
                r = simulate_carry(spot, perp, fbar, CarryConfig(leverage=lev), bpy)
                anns.append(r["annualized"]); dds.append(r["max_drawdown"])
                liqs += 1 if r["liquidated"] else 0
            if not anns:
                continue
            print(f"| {wlabel} | {lev:.0f}x | {statistics.median(anns)*100:+.1f} | "
                  f"{statistics.median(dds)*100:.1f} | {liqs}/{len(anns)} |")

    print("\n## How to read this\n")
    print("- Yield scales ~linearly with leverage; so does drawdown.")
    print("- 'liquidated' = the isolated perp short would have hit its maintenance")
    print("  margin during a rally (cross-account risk) -> needs margin top-ups or")
    print("  auto-deleverage. Delta-neutral protects PnL, NOT the isolated perp margin.")
    print("- Carry yield is a function of the funding REGIME, not of code cleverness.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
