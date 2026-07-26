"""Batch backtest over many symbols x 5m/15m on REAL data, in TWO fee scenarios
(taker vs maker), with a ROBUSTNESS gate that resists cherry-picking.

A (strategy, timeframe) only "passes" if it is positive on a MAJORITY of
symbols with a healthy median profit factor and enough trades. Running both
fee scenarios isolates the real question: is there NO edge, or is the edge
just eaten by costs?

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
TFS = [(5, 4), (15, 6)]          # (interval_minutes, history_months)
RISK_PCT = 0.005

# fee scenarios: (label, fee_per_side, slippage_per_fill)
SCENARIOS = [
    ("taker", 0.00055, 0.0005),  # market orders — realistic, conservative
    ("maker", 0.00020, 0.0001),  # limit entries — optimistic (assumes fills)
]

# Robustness gate (all must hold) — strict, to avoid fooling ourselves
MIN_POSITIVE_FRAC = 0.60
MIN_MEDIAN_PF = 1.20
MIN_MEDIAN_TRADES = 20


def backtest(interval, df, name, fee, slip):
    return Backtester(
        build(name),
        RiskConfig(risk_pct=RISK_PCT),
        BacktestConfig(fee=fee, slippage=slip, bars_per_year=bars_per_year_for(interval)),
    ).run(df)


def aggregate_and_report(results: dict, label: str) -> list:
    print(f"\n## Robustness — {label} fees\n")
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
        passed = (
            pos_frac >= MIN_POSITIVE_FRAC
            and med_pf >= MIN_MEDIAN_PF
            and med_tr >= MIN_MEDIAN_TRADES
        )
        if passed:
            winners.append((name, interval, med_pf, pos_frac, mean_ret))
        print(
            f"| {name} | {interval}m | {sum(1 for x in rets if x>0)}/{len(rets)} | "
            f"{med_pf:.2f} | {med_tr:.0f} | {mean_ret:+.1f} | {'YES' if passed else 'no'} |"
        )
    return winners


def main() -> int:
    # fetch every (symbol, interval) once, reuse across fee scenarios
    cache: dict[tuple, object] = {}
    print("# Strategy sweep — REAL Binance data, taker vs maker fees\n")
    print(f"symbols={SYMBOLS}  risk/trade={RISK_PCT*100:.2f}%\n")
    for interval, months in TFS:
        for symbol in SYMBOLS:
            try:
                cache[(symbol, interval)] = fetch_binance_vision_klines(
                    symbol, interval, months=months
                )
            except Exception as exc:  # noqa: BLE001
                print(f"FETCH FAILED {symbol} {interval}m: {type(exc).__name__} {str(exc)[:50]}")
                traceback.print_exc()

    all_winners = []
    for label, fee, slip in SCENARIOS:
        results: dict[tuple, list] = {}
        for (symbol, interval), df in cache.items():
            for name in REGISTRY:
                try:
                    rep, _, _ = backtest(interval, df, name, fee, slip)
                except Exception as exc:  # noqa: BLE001
                    print(f"RUN FAILED {symbol} {interval}m {name}: {str(exc)[:40]}")
                    continue
                results.setdefault((name, interval), []).append((symbol, rep))
        all_winners.append((label, aggregate_and_report(results, label)))

    print("\n## Verdict\n")
    any_win = False
    for label, winners in all_winners:
        if winners:
            any_win = True
            print(f"Under **{label}** fees, candidates that generalize on 5m/15m:")
            for name, interval, med_pf, pos, mret in sorted(winners, key=lambda w: -w[2]):
                print(f"  - **{name} @ {interval}m** — median PF {med_pf:.2f}, "
                      f"positive on {pos*100:.0f}% of symbols, mean ret {mret:+.1f}%")
    if not any_win:
        print("No strategy cleared the robustness gate under EITHER taker OR maker fees.")
        print("Honest read: the problem is not just cost — there is no generalizing")
        print("bar-based edge at 5-15m in these designs. Cutting fees does not save it.")
    else:
        print("\nNote: a maker-only edge needs a fill model before trusting it (limit")
        print("orders don't always fill). Validate walk-forward + on DEMO first.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
