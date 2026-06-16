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

## Funding-aware grid (REAL Binance funding, base vs fund vs tilt)

| variant | tf | symbols+ | median ret% | funding contribution |
|---|---|---|---|---|
| base | 15m / 30m | 0/6 · 1/6 | −1.4% / −3.4% | — |
| fund (real funding credited) | 15m / 30m | 0/6 · 1/6 | −1.4% / −3.4% | **≈ ±0.1%** |
| tilt (lean to carry side) | 15m / 30m | 0/6 · 1/6 | −2.7% / −5.5% | ≈ ±0.1% |

**Funding added ~nothing (±0.1%)** because a delta-neutral grid carries ~0 net
inventory, and funding accrues on NET position. Deliberately tilting to collect
funding made it WORSE (shorting to earn positive funding = shorting into the
rally that causes positive funding; directional loss > funding earned). This is
the textbook proof that funding harvest needs a SPOT hedge (long spot + short
perp), which a single futures account cannot do.

## Carry across funding regimes & leverage (median over 6 symbols)

| window | leverage | ann.yield% | maxDD% | perp-leg liquidations |
|---|---|---|---|---|
| recent ~8mo (dry funding) | 1x | +0.9 | −0.8 | 0/6 |
| recent | 3x | +2.8 | −2.2 | 1/6 |
| recent | 5x | +4.6 | −3.7 | 1/6 |
| **bull 2024H2→25 (high funding)** | **1x** | **+10.1** | **−0.9** | 2/6 |
| bull | 3x | +31.8 | −2.6 | 5/6 |
| bull | 5x | +55.4 | −4.1 | 6/6 |

**Read:** in a normal/high-funding regime, unleveraged carry yields ~+10%/yr at
<1% drawdown — a genuine low-risk return. Leverage scales yield ~linearly but
lights up perp-leg liquidations during rallies (3x: 5/6 symbols; 5x: 6/6) — the
isolated short perp hits maintenance margin before the offsetting spot gain is
realised. The real leverage risk is liquidation (needs margin top-ups), not the
(small) drawdown. Carry yield tracks the funding REGIME, not code cleverness.

## Delta-neutral funding carry (long spot + short perp) — the one real edge

Real spot + perp + funding, ~8 months, 1x, taker fees on both legs.

| mode | symbol | ann.yield% | funding% | basis% | maxDD% |
|---|---|---|---|---|---|
| static | BTC | +1.9 | +1.5 | ~0 | −0.4 |
| static | ETH | +1.5 | +1.2 | ~0 | −0.6 |
| static | SOL | −3.5 | −2.1 | ~0 | −3.5 |
| static | BNB | +0.4 | +0.5 | ~0 | −0.9 |
| static | XRP | −1.0 | −0.4 | ~0 | −1.0 |
| static | DOGE | +1.4 | +1.2 | ~0 | −0.5 |
| **static (median)** | — | **+0.9** | — | ~0 | **−0.8** |
| timed (toggle) | all | −25…−38 | +2 | — | −25 |

**Findings:**
1. Static delta-neutral carry is the ONLY positive-expectancy construct found:
   positive on 4/6 symbols, median +0.9%/yr, drawdown <1% — basis ≈ 0 confirms
   price risk is genuinely neutralised; income is pure funding.
2. Yield is small here because funding was historically LOW this window (even
   negative on SOL/XRP). Carry earns exactly what the market pays; in high-
   funding bull regimes the same construct historically yields 10–30%/yr.
3. "Timing" funding by toggling in/out is a FEE TRAP (80–130 toggles × two-leg
   costs = −25…−38%). Carry must be HELD, not traded.

**There is no low-risk high-return grail (proven 5 ways: directional, grid,
funding-grid, tilt, timed-carry). The honest edge is a safe carry whose yield
scales with the funding regime.**

At 5–30m on liquid crypto, **no bar-based strategy showed a positive
generalizing edge.** Direction-prediction loses; the grid (a primitive
market-maker) only breaks even. The realistic positive-expectancy path at low
TF is market-making INCOME (spread + funding + maker rebates), not direction
prediction — or moving to higher timeframes where direction has signal (4h).
