# Carry bot — delta-neutral funding harvester (long spot + short perp)

The one positive-expectancy construct found in this repo: hold spot, short the
perp, collect funding. Price risk ~cancels; income is the funding the short
perp receives every 8h. Yield tracks the funding regime (~1%/yr in a dry
window, ~10%/yr unleveraged in a high-funding bull — see `../BACKTEST_RESULTS.md`).

## Paper-trade it on real history (no keys, no risk)

```bash
pip install pandas numpy
python -m algo_engine.carry_bot.run --symbol BTCUSDT --months 8 --leverage 1
# a past high-funding window:
python -m algo_engine.carry_bot.run --symbol BTCUSDT --months 7 --leverage 3 --end-month 2025-02
```

Real CI paper runs (BTCUSDT):
- **1x, recent ~8mo:** +1.14% (funding +1.33%, fees 0.20%) — clean hold, 0 margin top-ups.
- **3x, 2024H2→25 bull:** +1.72%, but **113 margin top-ups then a safe auto-unwind**
  near perp liquidation. The risk rails protect capital and cap yield — leverage
  is not free in a rally.

## What the bot does each tick

1. **open** — buy spot notional N, short perp notional N at leverage L (delta ~0).
2. **collect funding** — credited to the short perp leg on each 8h settlement.
3. **keep delta neutral** — rebalance if it drifts past a threshold.
4. **defend the perp leg** — if its margin ratio nears maintenance, top up margin
   from cash; if it breaches, unwind safely.
5. **kill-switch** — unwind if account equity draws down past a limit.

All logic is in `bot.py` (pure, venue-injected). `venue.py::PaperVenue` simulates
spot+perp+funding in-process for tests and paper trading. Unit tests:
`../tests/test_carry_bot.py`.

## Going live (NOT wired here — by design)

`run.py --live` is intentionally disabled. To trade for real you must implement a
`Venue` adapter (e.g. Bybit unified account: spot buy + linear-perp short + read
funding/margin over REST/WS) and add your own order-confirmation + risk checks.
Recommended path: **Bybit Demo first** (paper money on the real venue), tiny size,
1x, watch the 8h funding settlements and the perp margin, then scale gradually.
Never run leverage you cannot margin-top-up during a rally.
