"""Batch backtest over several symbols x timeframes on REAL Bybit data.

Run (needs internet -> use the GitHub Actions runner):
    python -m algo_engine.scripts.run_batch

Prints a markdown results table and a short verdict. Designed to be read out
of a CI job log. Per-cell failures (e.g. an exchange 403) are caught so one
bad symbol never kills the whole sweep.
"""
from __future__ import annotations

import traceback

from algo_engine.backtest import Backtester, BacktestConfig, bars_per_year_for
from algo_engine.data import fetch_bybit_klines
from algo_engine.risk import RiskConfig
from algo_engine.strategies import REGISTRY, build

# (symbol, interval_minutes, history_days)
JOBS = [
    ("BTCUSDT", 5, 120),
    ("BTCUSDT", 15, 180),
    ("ETHUSDT", 5, 120),
    ("ETHUSDT", 15, 180),
    ("SOLUSDT", 5, 120),
    ("SOLUSDT", 15, 180),
    ("BTCUSDT", 1, 30),
    ("ETHUSDT", 1, 30),
]
RISK_PCT = 0.005
PF_BAR = 1.30  # profit-factor threshold below which we treat a result as "do not trade"


def run_one(symbol, interval, days):
    df = fetch_bybit_klines(symbol, interval, days=days)
    out = {}
    for name in REGISTRY:
        report, trades, _ = Backtester(
            build(name),
            RiskConfig(risk_pct=RISK_PCT),
            BacktestConfig(bars_per_year=bars_per_year_for(interval)),
        ).run(df)
        out[name] = (report, len(df))
    return out


def main() -> int:
    rows = []
    passes = []
    print("# Batch backtest — REAL Bybit data\n")
    print(f"risk/trade = {RISK_PCT*100:.2f}%  | fees+slippage applied | PF bar = {PF_BAR}\n")
    print("| symbol | tf | strategy | bars | trades | win% | PF | ret% | maxDD% | Sharpe | killed |")
    print("|---|---|---|---|---|---|---|---|---|---|---|")
    for symbol, interval, days in JOBS:
        try:
            res = run_one(symbol, interval, days)
        except Exception as exc:  # noqa: BLE001 — report and continue
            print(f"| {symbol} | {interval}m | — | — | FETCH/RUN FAILED: {type(exc).__name__} {str(exc)[:50]} |||||||")
            traceback.print_exc()
            continue
        for name, (rep, nbars) in res.items():
            pf = rep.profit_factor
            pf_str = "inf" if pf == float("inf") else f"{pf:.2f}"
            killed = "yes" if rep.extra.get("killed") else ""
            print(
                f"| {symbol} | {interval}m | {name} | {nbars} | {rep.n_trades} | "
                f"{rep.win_rate*100:.1f} | {pf_str} | {rep.total_return*100:+.1f} | "
                f"{rep.max_drawdown*100:.1f} | {rep.sharpe:.2f} | {killed} |"
            )
            rows.append((symbol, interval, name, rep))
            if rep.n_trades >= 30 and pf >= PF_BAR and rep.total_return > 0:
                passes.append((symbol, interval, name, rep))

    print("\n## Verdict\n")
    if not rows:
        print("No results — data fetch failed for every job (likely exchange egress block).")
        return 0
    if passes:
        print(f"{len(passes)} configuration(s) cleared the bar (PF >= {PF_BAR}, positive, >=30 trades):\n")
        for s, i, n, rep in sorted(passes, key=lambda r: -r[3].profit_factor):
            print(f"  - **{n} on {s} {i}m** -> {rep.pretty()}")
        print("\nNext gate: confirm on DEMO before any live size. A backtest edge is necessary, not sufficient.")
    else:
        print("NONE of the tested configurations cleared the bar (PF >= 1.30, positive, >=30 trades).")
        print("Honest read: on this data + these params, neither strategy shows a tradeable edge.")
        print("Options: try other symbols, tune params, or accept that this regime isn't tradeable by these rules.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
