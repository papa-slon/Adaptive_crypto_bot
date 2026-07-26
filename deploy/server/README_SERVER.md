# Installing the carry bot on the Singapore host (54.179.188.61)

## What is already on that box

| What | Where | Port | Leave alone |
|---|---|---|---|
| existing bot | `/home/ubuntu/apps/bot/` | 8000 | yes |
| turtle bingx | `/home/ubuntu/apps/turtle_bingx/` | — | yes |
| turtle journal | same dir | 8080 | yes |
| **carry bot (this)** | `/home/ubuntu/apps/carry_bot/` | **8090** | — |

Nothing here touches ports 8000/8080 or any existing unit. The installer only
adds; it refuses to overwrite a non-git directory and aborts if 8090 is taken.

## One command

```bash
ssh -i "C:\Users\maxib\GTE BOT\keys\key_server_bot_singapur.pem" ubuntu@54.179.188.61 \
  'curl -fsSL https://raw.githubusercontent.com/papa-slon/Adaptive_crypto_bot/claude/crypto-algo-trading-bot-sti7oe/deploy/server/install.sh | bash'
```

Rehearse it first if you want — this changes nothing:

```bash
ssh -i "…key.pem" ubuntu@54.179.188.61 \
  'curl -fsSL https://raw.githubusercontent.com/papa-slon/Adaptive_crypto_bot/claude/crypto-algo-trading-bot-sti7oe/deploy/server/install.sh | bash -s -- --dry-run'
```

The installer clones the branch, builds a venv, **runs the bot's 80 offline
tests on the server**, writes an `.env` with a freshly generated admin password,
installs both systemd units — and stops there. Nothing starts on its own.

## Then, in order

```bash
# 1) dashboard only — read-only, places no orders
sudo systemctl start carry-dashboard.service

# 2) enter the exchange keys in the browser (never over SSH)
#    http://54.179.188.61:8090/settings
#    password = BOT_ADMIN_PASSWORD printed by the installer
#    (open 8090 in the AWS security group, or tunnel:
#     ssh -L 8090:127.0.0.1:8090 ubuntu@54.179.188.61 )

# 3) only now the bot itself
sudo systemctl start carry-bot.service
journalctl -u carry-bot -f
```

## Admin

```bash
sudo systemctl stop carry-bot          # unwinds both legs, 90s grace
sudo systemctl restart carry-bot
journalctl -u carry-bot -f
tail -f /home/ubuntu/apps/carry_bot/logs/carry_bot.log

# update after new commits
cd /home/ubuntu/apps/carry_bot && git pull && sudo systemctl restart carry-bot carry-dashboard
```

## Stopping the turtle bot (separate, authorised)

```bash
cd /home/ubuntu/apps/turtle_bingx && .venv/bin/python main.py status   # look first
sudo systemctl stop turtle-bot.service
sudo systemctl disable turtle-bot.service        # reversible, not a deletion
```

Its stops and take-profits live on the exchange, so open positions stay
protected — but the stop stops trailing. Decide whether to close them by hand.
Bring it back with `sudo systemctl enable --now turtle-bot.service`.

## What to expect from this bot

It is a funding-carry bot, not a directional one: long spot + short perp on the
same coin, so price moves cancel and the income is the funding the perp market
pays every 8h. It scans and picks the coins itself.

Measured on 12 months of real funding across 18 coins, on capital actually
employed (spot notional + perp margin): **about +1.1%/yr for the rotating
scanner versus +1.5%/yr for simply holding BTC**, drawdown under 0.3%. That is
a money-market-like return in the current, dry funding regime — the same
machine pays several times more when funding is high. Run it on demo to see the
plumbing work; do not expect it to make money at today's rates.
