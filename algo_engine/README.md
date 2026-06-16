# algo_engine — a clean, tested crypto trading engine

Built **alongside** the existing `src/` and `adaptive_crypto_bot/` code without
touching it. This is the part that actually trades and that you can actually
verify.

## The honest part (read this first)

**Nobody can hand you a guaranteed-profitable bot.** On 1–5–15m timeframes,
fees + slippage + noise destroy most retail strategies. If something promises
profit "out of the box," it is lying.

What *does* work is a discipline, not a magic signal:

1. a **simple, understandable** strategy,
2. **strict risk control** (0.5%/trade, daily-loss limit, drawdown kill-switch),
3. a **realistic backtest** so you see the edge — or its absence — *before*
   risking a cent, then **demo**, then (only by your decision) live.

This repo gives you all three. The edge is something **you verify**, here and on
demo. The engine just makes that verification honest and the downside bounded.

## Install

```bash
pip install pandas numpy pyyaml pytest
```

## Quickstart

```bash
# 1) Backtest both strategies on REAL Bybit history (public data, no keys):
python -m algo_engine.cli compare --symbol BTCUSDT --interval 5 --days 60

# 2) Backtest one, save the equity curve:
python -m algo_engine.cli backtest --strategy trend_breakout --symbol ETHUSDT --interval 15 --days 90 --save-equity eq.csv

# 3) Sanity-check the mechanics offline (synthetic data, never the network):
python -m algo_engine.cli compare --synthetic 6000

# 4) Run the live loop on Bybit DEMO (auto + kill-switch):
export BYBIT_API_KEY=...      # your DEMO keys
export BYBIT_API_SECRET=...
python -m algo_engine.cli live --config algo_engine/configs/default.yaml
```

Without `BYBIT_API_KEY/SECRET` the live loop runs in **PAPER** mode (simulated
fills, zero risk). With demo keys it trades the **Bybit demo** account.

## The report you get

```
trades=99  win%=37.4  PF=1.04  exp=+1.10USDT  ret=-1.9%  maxDD=-9.5%  Sharpe=-1.18  eq=9,815
```

- **PF (profit factor)** > 1 means gross wins outweigh gross losses. Below ~1.2
  on a backtest is noise; don't trade it.
- **maxDD** is the worst peak-to-trough dip — your pain tolerance check.
- **exp** is average net PnL per trade (after fees). Negative = the strategy
  loses money on this data. That's the engine being honest, not broken.

## Safety (how you stay in control)

- **0.5% risk per trade** — position size is computed so that hitting the stop
  loses exactly 0.5% of equity. Nothing else sets size.
- **Daily loss limit** (−6%): no new entries after a bad day.
- **Kill-switch** (−25% from peak): flattens and stops everything.
- **Stop everything now**: create an empty file named `STOP` in the working
  dir, or press Ctrl+C.
- **Demo by default.** Live (real money) needs `demo: false` in the config
  **and** `export AE_ALLOW_LIVE=1` — two deliberate locks.
- **Keys only via env**, never in files, never logged.

## How it's wired

```
data.py          real Bybit klines (public) + cache + synthetic generator
indicators.py    EMA / ATR / RSI / ADX / z-score / Donchian — vectorized, causal
strategies/      trend_breakout (ride trends) + mean_reversion (fade extremes)
risk.py          sizing + daily-loss gate + drawdown kill-switch  <-- your safety
backtest.py      look-ahead-free, fees+slippage, next-bar fills
metrics.py       win%, profit factor, expectancy, maxDD, Sharpe
broker/          paper (simulated) + bybit (real demo/live, HMAC-signed)
live.py          auto loop: new bar -> signal -> risk -> order, with kill-switch
cli.py           backtest / compare / fetch / live
```

The same `Strategy` + `RiskManager` run in both backtest and live, so what you
test is what you trade.

## Recommended workflow

1. `compare` across several symbols and periods (60–180 days). Look for PF > 1.3
   and a drawdown you can stomach. **If nothing clears the bar, don't trade it.**
2. Run `live` on **demo** for a few days. Confirm the live log matches what the
   backtest implied.
3. Only then, if you choose, flip to live with small size — the two locks above
   make that an explicit decision, never an accident.

## Tests

```bash
python -m pytest algo_engine/tests/ -q
```

Indicators, risk math, backtest no-look-ahead, fees, kill-switch, and the paper
broker are all covered and run fully offline.
