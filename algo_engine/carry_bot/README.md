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

## Live on Bybit Demo (real orders, paper money)

Defaults to **Bybit DEMO**; mainnet needs explicit `--mainnet --yes-mainnet`.

```bash
# 1) read-only connectivity + balance check (no orders)
export BYBIT_API_KEY=...  BYBIT_API_SECRET=...     # Bybit Demo keys
python -m algo_engine.carry_bot.run --venue bybit-demo --symbol BTCUSDT

# 2) live demo loop (REAL demo orders): open carry, collect funding, defend margin
python -m algo_engine.carry_bot.live --symbol BTCUSDT --notional 20 --leverage 1
#   --poll-seconds 30     how often to monitor/defend
#   --max-minutes 120     auto-unwind after N minutes (optional)
#   Ctrl-C                unwinds cleanly
```

It logs every action + a status line to stdout AND `logs/carry_bot.log` — send me
that file if anything misbehaves.

Safety built in: read-only until trading is explicitly enabled; demo base URL by
default; aborts if the demo wallet can't fund the carry; best-effort isolated
margin so top-ups work; near-liquidation auto-unwind + equity drawdown
kill-switch as backstops. Funding is settled by the exchange (reflected in
equity/margin) — not applied manually.

Start tiny (e.g. `--notional 20 --leverage 1`), watch a couple of 8h funding
settlements, then scale. Never run leverage you can't margin-top-up in a rally.
