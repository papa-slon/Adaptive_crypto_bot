"""Run the carry bot in PAPER mode over real historical spot+perp+funding, so
you can watch it open, collect funding, defend margin, and report a result —
without touching real money.

    python -m algo_engine.carry_bot.run --symbol BTCUSDT --months 8 --leverage 1

Live trading is intentionally NOT wired here: a real venue adapter must be
implemented + explicitly enabled, and every order must go through your own
confirmation + risk checks. This entry point can only paper-trade.
"""
from __future__ import annotations

import argparse

from algo_engine.carry_bot.bot import CarryBot, CarryBotConfig
from algo_engine.carry_bot.venue import PaperVenue
from algo_engine.data import (
    align_funding_to_bars,
    fetch_binance_vision_funding,
    fetch_binance_vision_klines,
)


def run_paper(symbol: str, months: int, leverage: float, end_month: str | None) -> int:
    spot = fetch_binance_vision_klines(symbol, 60, months=months, market="spot",
                                       end_month=end_month)["close"]
    perp = fetch_binance_vision_klines(symbol, 60, months=months, market="futures/um",
                                       end_month=end_month)["close"]
    idx = spot.index.intersection(perp.index)
    spot, perp = spot.reindex(idx), perp.reindex(idx)
    fnd = fetch_binance_vision_funding(symbol, months=months, end_month=end_month)
    fbar = align_funding_to_bars(spot.index, fnd)

    v = PaperVenue(price=float(perp.iloc[0]), cash=1.0)
    bot = CarryBot(v, CarryBotConfig(notional=1.0, leverage=leverage))
    print(f"# PAPER carry — {symbol}, {len(spot)} bars, leverage {leverage:g}x\n")
    for a in bot.open():
        print(" ", a)

    topups = rebalances = funding_events = 0
    for i in range(1, len(spot)):
        v.set_price(float(perp.iloc[i]))
        if fbar[i] != 0.0:
            v.apply_funding(float(fbar[i])); funding_events += 1
        for a in bot.step():
            if a.startswith("TOP-UP"):
                topups += 1
            elif a.startswith("REBALANCE"):
                rebalances += 1
            elif a.startswith("UNWOUND"):
                print(" ", a)
        if bot.state == "FLAT":
            break

    for a in bot.unwind("end of data"):
        print(" ", a)
    eq = v.equity()
    print(f"\nfinal equity      : {eq:.5f}  (start 1.00000)")
    print(f"total return      : {(eq-1)*100:+.2f}%")
    print(f"funding collected : {v.funding_collected*100:+.2f}% of 1x notional")
    print(f"fees paid         : {v.fees_paid*100:.2f}%")
    print(f"funding events    : {funding_events} | margin top-ups: {topups} | rebalances: {rebalances}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbol", default="BTCUSDT")
    ap.add_argument("--months", type=int, default=8)
    ap.add_argument("--leverage", type=float, default=1.0)
    ap.add_argument("--end-month", default=None, help="YYYY-MM to paper-trade a past window")
    ap.add_argument("--live", action="store_true",
                    help="(disabled) live trading is not wired in this entry point")
    args = ap.parse_args()
    if args.live:
        print("LIVE mode is intentionally not implemented here. Paper only.")
        return 2
    return run_paper(args.symbol, args.months, args.leverage, args.end_month)


if __name__ == "__main__":
    raise SystemExit(main())
