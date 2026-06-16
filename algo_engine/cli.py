"""Command line:  python -m algo_engine.cli <command> ...

    backtest   run one strategy on history, print the honest report
    compare    run BOTH strategies on the same data, side by side
    fetch      download + cache klines from Bybit (public)
    live       start the auto + kill-switch loop (paper unless keys in env)

Examples:
    python -m algo_engine.cli compare --symbol BTCUSDT --interval 5 --days 60
    python -m algo_engine.cli backtest --strategy mean_reversion --synthetic
    python -m algo_engine.cli live --config algo_engine/configs/default.yaml
"""
from __future__ import annotations

import argparse
import logging
import sys

from . import data
from .backtest import Backtester, BacktestConfig, bars_per_year_for
from .risk import RiskConfig
from .strategies import REGISTRY, build as build_strategy


def _load_df(args):
    if args.synthetic:
        return data.synthetic_ohlcv(
            n=args.synthetic, interval_min=args.interval, trend_strength=0.15
        )
    return data.load(args.symbol, args.interval, days=args.days, refresh=args.refresh)


def _run_one(name: str, df, args):
    strat = build_strategy(name)
    bt = Backtester(
        strat,
        RiskConfig(risk_pct=args.risk),
        BacktestConfig(
            initial_equity=args.equity,
            fee=args.fee,
            slippage=args.slippage,
            bars_per_year=bars_per_year_for(args.interval),
        ),
    )
    return bt.run(df)


def cmd_backtest(args):
    df = _load_df(args)
    report, trades, equity = _run_one(args.strategy, df, args)
    print(f"\n=== {args.strategy} on {args.symbol} {args.interval}m  ({len(df)} bars) ===")
    print(report.pretty())
    if report.extra.get("killed"):
        print(f"  !! KILL-SWITCH fired: {report.extra['kill_reason']}")
    if args.save_equity:
        equity.to_csv(args.save_equity, index_label="ts")
        print(f"  equity curve -> {args.save_equity}")


def cmd_compare(args):
    df = _load_df(args)
    print(f"\n=== compare on {args.symbol} {args.interval}m  ({len(df)} bars) ===")
    print(f"{'strategy':<16} {'report'}")
    rows = []
    for name in REGISTRY:
        report, _, _ = _run_one(name, df, args)
        rows.append((name, report))
        print(f"{name:<16} {report.pretty()}")
    best = max(rows, key=lambda r: (r[1].profit_factor if r[1].n_trades else -1, r[1].total_return))
    print(f"\n-> by profit factor + return, the stronger sample here is: {best[0]}")
    print("   (sample, not proof — re-run across symbols/periods and on demo before trusting it)")


def cmd_fetch(args):
    df = data.load(args.symbol, args.interval, days=args.days, refresh=True)
    print(f"cached {len(df)} bars of {args.symbol} {args.interval}m ({args.days}d)")


def cmd_live(args):
    from .config import EngineConfig
    from .live import run

    cfg = EngineConfig.from_yaml(args.config) if args.config else EngineConfig()
    run(cfg, max_cycles=args.max_cycles)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="algo_engine", description=__doc__)
    sub = p.add_subparsers(dest="cmd", required=True)

    def common(sp):
        sp.add_argument("--symbol", default="BTCUSDT")
        sp.add_argument("--interval", type=int, default=5, help="minutes: 1/3/5/15/30/60/240")
        sp.add_argument("--days", type=float, default=30.0)
        sp.add_argument("--synthetic", type=int, default=0, help="N synthetic bars instead of real")
        sp.add_argument("--refresh", action="store_true", help="ignore cache, re-download")
        sp.add_argument("--risk", type=float, default=0.005, help="fraction risked per trade")
        sp.add_argument("--equity", type=float, default=10_000.0)
        sp.add_argument("--fee", type=float, default=0.00055)
        sp.add_argument("--slippage", type=float, default=0.0005)

    bt = sub.add_parser("backtest", help="run one strategy")
    common(bt)
    bt.add_argument("--strategy", default="trend_breakout", choices=list(REGISTRY))
    bt.add_argument("--save-equity", default=None)
    bt.set_defaults(func=cmd_backtest)

    cp = sub.add_parser("compare", help="run all strategies side by side")
    common(cp)
    cp.set_defaults(func=cmd_compare)

    ft = sub.add_parser("fetch", help="download + cache klines")
    ft.add_argument("--symbol", default="BTCUSDT")
    ft.add_argument("--interval", type=int, default=5)
    ft.add_argument("--days", type=float, default=30.0)
    ft.set_defaults(func=cmd_fetch)

    lv = sub.add_parser("live", help="start the live/demo loop")
    lv.add_argument("--config", default=None, help="YAML config path")
    lv.add_argument("--max-cycles", type=int, default=None, help="stop after N cycles (testing)")
    lv.set_defaults(func=cmd_live)
    return p


def main(argv=None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    args = build_parser().parse_args(argv)
    args.func(args)
    return 0


if __name__ == "__main__":
    sys.exit(main())
