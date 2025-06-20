
# 03 Trend‑TF Agent

Trend‑following agent operating on m5 bars.

## Entry Conditions
1. EMA21 > EMA200  (bull)  **or**  EMA21 < EMA200 (bear)
2. Daily VWAP slope > 0 (bull) / < 0 (bear)  – measured by Kalman angle
3. Hidden‑Markov probability of trend regime `p_trend > 0.5`

## Exit / Management
* Initial stop = 1.2 ATR
* Move stop to trailing 1 ATR after +1 ATR favourable move
* Time‑out 80 bars

See `docs/03_trend_tf.md` for full maths and diagrams.
