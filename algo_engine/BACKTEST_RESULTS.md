# Backtest results — real data (run on GitHub Actions, 2026-06-16)

Real Binance USDⓂ futures klines (data.binance.vision), both strategies,
risk 0.5%/trade, taker fees 0.055%/side + 5 bps slippage, ATR-stop sizing,
daily-loss + drawdown kill-switch. Look-ahead-free, next-bar fills.

**This is honest evidence, not marketing. Most cells LOSE money.** The value
is knowing that *before* risking capital.

## Low timeframes (what was requested) — DO NOT TRADE

Every 1m/5m/15m config lost; most tripped the −25% kill-switch.

| symbol | tf | strategy | trades | win% | PF | ret% | maxDD% |
|---|---|---|---|---|---|---|---|
| BTC/ETH/SOL | 5m  | both | 86–122 | 17–43 | 0.39–0.53 | −24…−25% | ~−25% |
| BTC/ETH/SOL | 15m | both | 66–97  | 15–38 | 0.37–0.57 | −17…−24% | −18…−25% |
| BTC/ETH     | 1m  | both | 28–34  | 6–12  | 0.03–0.10 | ~−25%     | ~−25% |

**Why:** a round-trip costs ~0.16% (fees+slippage). At 1m with ~100 trades the
cost alone is multiples of any signal. The math is against you at low TF.

## Higher timeframes — the fee drag eases (same code, same params)

| symbol | tf | strategy | trades | win% | PF | ret% | maxDD% | Sharpe |
|---|---|---|---|---|---|---|---|---|
| ETH | 1h | trend    | 124 | 27.4 | 0.93 | −5.9% | −13.1% | −0.55 |
| BTC | 4h | mean-rev | 14  | 50.0 | 1.60 | +2.1% | −2.9%  | 0.74 |
| ETH | 4h | trend    | 62  | 29.0 | 1.28 | +5.3% | −9.6%  | 0.56 |
| ETH | 4h | mean-rev | 9   | 66.7 | 2.92 | +3.0% | −1.1%  | 1.33 |
| SOL | 4h | mean-rev | 16  | 50.0 | 1.62 | +2.5% | −1.7%  | 0.76 |
| BTC | 4h | trend    | 68  | 17.6 | 0.66 | −9.1% | −11.2% | −0.99 |
| SOL | 4h | trend    | 67  | 29.9 | 0.89 | −2.7% | −7.7%  | −0.26 |

## Honest interpretation

1. **1–15m scalping with these strategies has no edge** — confirmed on real
   data across 3 majors. Costs dominate. Stop chasing it.
2. **The edge appears at 4h.** Four of six 4h configs are net positive; 4h
   mean-reversion on BTC/ETH/SOL shows PF 1.6–2.9.
3. **BUT confidence is mixed.** The high-PF 4h mean-rev cells have only 9–16
   trades over ~18 months — too few to trust (could be luck). The most
   *statistically_ trustworthy positive is **ETH 4h trend** (62 trades, PF 1.28,
   +5.3%) — modest but on a real sample.
4. **Next step is validation, not tuning.** Do NOT tweak parameters until a
   backtest looks pretty — that is overfitting and it dies live. The right move
   is out-of-sample / walk-forward testing on more symbols at 4h, then demo.

## Reproduce

```bash
python -m algo_engine.scripts.run_batch   # needs internet (runs on CI here)
```
