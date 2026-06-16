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

## Final sweep — 6 strategies x 6 symbols x 5m/15m x (taker AND maker fees)

Strategies tested: trend_breakout, mean_reversion, squeeze_breakout,
trend_pullback, vwap_reversion, range_rejection (Gerchik-style false breakout).
Symbols: BTC, ETH, SOL, BNB, XRP, DOGE.

**Taker fees:** 0/6 symbols positive for EVERY strategy at both 5m and 15m
(median PF 0.34–0.50).

**Maker fees (cut ~3x):** better, but still no pass — best was trend_breakout
15m (median PF 0.92, still negative; 1/6 symbols positive). Everything else
0–1/6, median PF 0.59–0.92.

**Conclusion (evidence-backed): there is no generalizing bar-based edge at
5–15m in any of these designs, and it is NOT merely a fee problem — cutting
fees to maker levels does not cross the line.** At 5–15m, exploitable patterns
in liquid crypto are competed away by latency/HFT participants; a retail
bar-based bot has no structural edge there. This is market structure, not a
coding failure.

Where a retail systematic bot DID show life: **4h** (see the higher-TF table
above — 4 of 6 configs net positive, though low trade count = low confidence).

## Reproduce

```bash
python -m algo_engine.scripts.run_batch   # needs internet (runs on CI here)
```

## Adaptive grid (15m/30m, 6 symbols, maker-ish fees — OPTIMISTIC fills)

3 grid configs x 6 symbols x {15m, 30m}. Robustness gate NOT cleared, but the
behaviour is fundamentally different from the directional strategies:

| config | tf | symbols+ | median ret% | kills |
|---|---|---|---|---|
| grid_notrend | 15m / 30m | 2/6 · 0/6 | −0.5% · −4.0% | 0/6 · 0/6 |
| grid_tight   | 15m / 30m | 0/6 · 1/6 | −1.8% · −3.2% | 0/6 · 0/6 |
| grid_wide    | 15m / 30m | 1/6 · 2/6 | −0.5% · −3.2% | 0/6 · 0/6 |

**Key takeaway:** the directional strategies blew up to −25% (kill-switch). The
grid NEVER blew up (0 kills / 36 runs) and sits ~flat (−0.5% on 15m). It is the
closest thing to break-even found at low TF — costs + mild trend-bleed keep it
just under zero. A market-maker that is ~flat on price needs an INCOME source
(maker rebates and/or funding) to cross into positive expectancy.

## Overall conclusion (after directional x6, grid x3, taker+maker, 6 symbols)

At 5–30m on liquid crypto, **no bar-based strategy showed a positive
generalizing edge.** Direction-prediction loses; the grid (a primitive
market-maker) only breaks even. The realistic positive-expectancy path at low
TF is market-making INCOME (spread + funding + maker rebates), not direction
prediction — or moving to higher timeframes where direction has signal (4h).
