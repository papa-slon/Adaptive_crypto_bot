# Carry bot — delta-neutral funding harvester

Buy spot, short the same notional of the perp, collect the funding the perp
market pays every 8h. Price risk cancels between the legs, so the income is the
funding, not a directional bet. This is the only positive-expectancy construct
found in this repo (see `../BACKTEST_RESULTS.md` for what did NOT work).

## Two ways to run it

**Autopilot (default) — the bot picks the coins.** Scans the venue's funding
rates, ranks them, opens the best payers, rotates when something is clearly
better. You set capital and slot count; you never pick a symbol.

```bash
export BINGX_API_KEY=...  BINGX_API_SECRET=...
python -m algo_engine.carry_bot.autopilot --venue bingx-demo --capital 200 --slots 3 --leverage 1
```

**Single symbol** — when you want one specific coin:

```bash
python -m algo_engine.carry_bot.live --venue bybit-demo --symbol BTCUSDT --notional 50 --leverage 1
```

Read-only connectivity check first (places no orders):

```bash
python -m algo_engine.carry_bot.run --venue bybit-demo --symbol BTCUSDT
```

## Dashboard

```bash
python -m algo_engine.carry_bot.dashboard --port 8080     # http://localhost:8080
```

Live realised APR (from funding actually booked), equity curve, per-slot table
(funding rate, ~APR, both legs, margin ratio, hold time) and an activity feed.
It has **no authentication** — on a public server run it with
`--host 127.0.0.1` and reach it over an SSH tunnel.

## How capital is used

A carry slot ties up the **spot notional plus the perp margin**:

    capital per slot = notional + notional / leverage

So `--capital 200 --slots 2 --leverage 1` puts 50 USDT of notional on each leg
of each slot. Leverage on the perp leg improves capital efficiency (2.0x capital
per unit notional at 1x → 1.2x at 5x) — it does **not** multiply exposure,
because the spot leg is always paid in full.

## Safety rails (all on by default)

| Rail | What it prevents |
|---|---|
| Preflight against real lot size / min qty / min notional | an order rejected for being too small |
| Transactional open with rollback | a naked, unhedged leg if the second order fails |
| Adopt-on-restart | a restarted container opening a *second* position |
| Sells only what the bot bought | ever touching coins you already held |
| Leverage-aware margin top-ups | self-deleveraging at high leverage, and liquidation |
| Refuses unrunnable leverage | posting margin too close to the maintenance ratio |
| Drawdown kill-switch | an unbounded loss in a bad funding regime |
| Anti-churn rotation | the fee trap of switching coins on every wobble |
| Demo endpoints by default | pointing at real money by accident |

## Selection rules (scanner)

A coin is a candidate only if its trailing funding is **positive** (we are short
the perp, so longs must be paying us), it has enough observed settlements, and
its funding is not a one-off spike (`std/mean` capped). Ranking is
stability-weighted, so a steady 0.01% beats a lottery ticket with the same mean.
The same `rank_candidates` runs in the backtest and live, so what is measured is
what is traded.

## Validation status

- Bybit adapter: signing verified offline against a reference HMAC; order
  payloads inspected. **Not** exercised against the live venue from here.
- BingX adapter: written without network access — see the module docstring for
  the exact response fields to confirm on the first VST/demo run.
- Everything else: 62 offline tests.

Start on demo, 1x, small capital. Watch a couple of 8h settlements before scaling.
