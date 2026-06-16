# Deploy the carry bot on a server (Bybit Demo)

The bot must run on an always-on machine (it holds a position). It cannot run
inside this AI sandbox (ephemeral + no exchange network) and must NOT run in CI
(GitHub runners can't reach Bybit, and a cron job would orphan the position).
Use any cheap always-on Linux VPS ($4–6/mo is plenty). Keys live ONLY in the
server's `.env` — never in chat, never in git.

## One-time setup on the VPS

```bash
# 1) install docker (Ubuntu/Debian)
curl -fsSL https://get.docker.com | sh

# 2) get the code
git clone https://github.com/papa-slon/Adaptive_crypto_bot.git
cd Adaptive_crypto_bot
git checkout claude/crypto-algo-trading-bot-sti7oe

# 3) configure: copy the template and fill in DEMO keys + sizing
cd deploy
cp .env.example .env
nano .env        # paste BYBIT_API_KEY / BYBIT_API_SECRET, set CARRY_NOTIONAL etc.
```

## Run it

```bash
# read-only connectivity check first (no orders):
docker compose run --rm --entrypoint python carry-bot \
  -m algo_engine.carry_bot.run --venue bybit-demo --symbol BTCUSDT

# then start the live demo bot in the background, auto-restarting:
docker compose up -d --build

# watch it:
docker compose logs -f          # live output
tail -f logs/carry_bot.log      # persisted log (send this if something breaks)

# stop it (unwinds within the 30s grace period):
docker compose down
```

## Safety recap

- Demo base URL by default; mainnet needs `--mainnet --yes-mainnet` (not set here).
- Aborts at startup if the demo wallet can't fund the carry.
- `restart: unless-stopped` + a resilient loop (transient errors retry with
  backoff; a sustained error streak triggers a safe unwind).
- Near-liquidation auto-unwind + equity drawdown kill-switch are always on.
- Start `CARRY_NOTIONAL=20`, `CARRY_LEVERAGE=1`. Scale only after you've watched
  a few 8h funding settlements behave.

If anything misbehaves, grab `deploy/logs/carry_bot.log` and send it over.
