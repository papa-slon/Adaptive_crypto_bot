"""Batch backtest over many symbols x 5m/15m on REAL data, with a ROBUSTNESS
gate that resists cherry-picking.

A (strategy, timeframe) only "passes" if it is positive on a MAJORITY of
symbols with a healthy median profit factor and enough trades — i.e. a real,
generalizing edge, not one lucky coin.

Run (needs internet -> GitHub runner):  python -m algo_engine.scripts.run_batch
"""
from __future__ import annotations

import statistics
import traceback

from algo_engine.backtest import Backtester, BacktestConfig, bars_per_year_for
from algo_engine.data import fetch_binance_vision_klines
from algo_engine.risk import RiskConfig
from algo_engine.strategies import REGISTRY, build

SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT", "DOGEUSDT"]
# (interval_minutes, history_months)
TFS = [(5, 4), (15, 6)]
RISK_PCT = 0.005

# Robustness gate (all must hold) — deliberately strict to avoid fooling ourselves
MIN_POSITIVE_FRAC = 0.60   # positive on >= 60% of symbols
MIN_MEDIAN_PF = 1.20       # median profit factor across symbols
MIN_MEDIAN_TRADES = 20     # enough activity to be meaningful


def backtest(symbol, interval, df, name):
    return Backtester(
        build(name),
        RiskConfig(risk_pct=RISK_PCT),
        BacktestConfig(bars_per_year=bars_per_year_for(interval)),
    ).run(df)


def main() -> int:
    # results[(name, interval)] = list of (symbol, report)
    results: dict[tuple, list] = {}
    print("# Smarter-strategy sweep — REAL Binance data (5m/15m)\n")
    print(f"symbols={SYMBOLS}  risk/trade={RISK_PCT*100:.2f}%  fees+slippage applied\n")
    print("| symbol | tf | strategy | trades | win% | PF | ret% | maxDD% |")
    print("|---|---|---|---|---|---|---|---|")
    for interval, months in TFS:
        for symbol in SYMBOLS:
            try:
                df = fetch_binance_vision_klines(symbol, interval, months=months)
            except Exception as exc:  # noqa: BLE001
                print(f"| {symbol} | {interval}m | FETCH FAILED: {type(exc).__name__} {str(exc)[:40]} ||||||")
                traceback.print_exc()
                continue
            for name in REGISTRY:
                try:
                    rep, trades, _ = backtest(symbol, interval, df, name)
                except Exception as exc:  # noqa: BLE001
                    print(f"| {symbol} | {interval}m | {name} RUN FAILED {str(exc)[:30]} ||||||")
                    continue
                pf = rep.profit_factor
                pf_s = "inf" if pf == float("inf") else f"{pf:.2f}"
                print(
                    f"| {symbol} | {interval}m | {name} | {rep.n_trades} | {rep.win_rate*100:.0f} | "
                    f"{pf_s} | {rep.total_return*100:+.1f} | {rep.max_drawdown*100:.1f} |"
                )
                results.setdefault((name, interval), []).append((symbol, rep))

    # ---- robustness aggregation ----
    print("\n## Robustness (aggregated across symbols)\n")
    print("| strategy | tf | symbols+ | median PF | median trades | mean ret% | PASS |")
    print("|---|---|---|---|---|---|---|")
    winners = []
    for (name, interval), rows in sorted(results.items()):
        pfs = [r.profit_factor for _, r in rows if r.profit_factor != float("inf")]
        rets = [r.total_return for _, r in rows]
        trs = [r.n_trades for _, r in rows]
        pos_frac = sum(1 for x in rets if x > 0) / len(rets)
        med_pf = statistics.median(pfs) if pfs else 0.0
        med_tr = statistics.median(trs)
        mean_ret = statistics.mean(rets) * 100
        passed = pos_frac >= MIN_POSITIVE_FRAC and med_pf >= MIN_MEDIAN_PF and med_tr >= MIN_MEDIAN_TRADES
        if passed:
            winners.append((name, interval, med_pf, pos_frac, mean_ret))
        print(
            f"| {name} | {interval}m | {sum(1 for x in rets if x>0)}/{len(rets)} | "
            f"{med_pf:.2f} | {med_tr:.0f} | {mean_ret:+.1f} | {'YES' if passed else 'no'} |"
        )

    print("\n## Verdict\n")
    if winners:
        print("Strategies that generalize across symbols on 5m/15m (real edge candidates):\n")
        for name, interval, med_pf, pos, mret in sorted(winners, key=lambda w: -w[2]):
            print(f"  - **{name} @ {interval}m** — median PF {med_pf:.2f}, positive on "
                  f"{pos*100:.0f}% of symbols, mean ret {mret:+.1f}%")
        print("\nNext gate: walk-forward (out-of-sample) + DEMO before any live size.")
    else:
        print("No strategy cleared the robustness gate (positive on >=60% symbols, "
              "median PF >=1.20, median trades >=20) on 5m/15m.")
        print("Honest read: still no GENERALIZING edge at 5-15m with these designs.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
