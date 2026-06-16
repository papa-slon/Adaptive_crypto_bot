"""Live carry-bot loop against Bybit Demo (real orders on paper money).

Flow:
  1. read BYBIT_API_KEY / BYBIT_API_SECRET from env (Demo keys),
  2. connectivity + balance check; abort if the wallet can't fund the carry,
  3. best-effort switch the perp symbol to ISOLATED margin (so margin top-ups
     work); the near-liquidation unwind is the backstop if that's unavailable,
  4. OPEN the carry (real demo orders), then poll every `poll_seconds`:
        bot.step() -> defend perp margin / keep delta neutral / dd kill-switch,
     logging a status line to stdout AND logs/carry_bot.log,
  5. Ctrl-C or the kill-switch -> unwind cleanly.

Funding is settled by the exchange (reflected in equity/margin) — the bot does
NOT apply it manually here, unlike the paper backtest.

Defaults to Bybit DEMO. Mainnet requires explicit --mainnet AND --yes-mainnet.
NOT verified from this sandbox (no network); validate on Demo, small size, 1x.
"""
from __future__ import annotations

import argparse
import logging
import os
import time

from algo_engine.carry_bot.bot import CarryBot, CarryBotConfig
from algo_engine.carry_bot.bybit_venue import DEMO_BASE, MAINNET_BASE, BybitVenue

LOG_PATH = "logs/carry_bot.log"


def _logger() -> logging.Logger:
    os.makedirs("logs", exist_ok=True)
    lg = logging.getLogger("carry_bot")
    lg.setLevel(logging.INFO)
    if not lg.handlers:
        fmt = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
        fh = logging.FileHandler(LOG_PATH, encoding="utf-8"); fh.setFormatter(fmt)
        sh = logging.StreamHandler(); sh.setFormatter(fmt)
        lg.addHandler(fh); lg.addHandler(sh)
    return lg


def resolve_keys() -> tuple[str, str] | None:
    k, s = os.environ.get("BYBIT_API_KEY"), os.environ.get("BYBIT_API_SECRET")
    return (k, s) if k and s else None


def run_live(symbol: str, notional: float, leverage: float, poll_seconds: float,
             base_url: str, max_minutes: float | None = None) -> int:
    keys = resolve_keys()
    if not keys:
        print("set BYBIT_API_KEY and BYBIT_API_SECRET (Bybit Demo keys) in your env.")
        return 2
    log = _logger()
    venue = BybitVenue(*keys, symbol=symbol, base_url=base_url,
                       enable_trading=True, leverage=leverage)

    # 1) connectivity + funding check (no orders yet)
    info = venue.connectivity_check()
    need = notional + notional / max(leverage, 1.0)     # spot + perp margin (USDT)
    log.info("venue=%s %s mark=%s USDT=%.2f need~%.2f",
             info["base_url"], symbol, info["mark_price"], info["usdt_balance"], need)
    if info["usdt_balance"] < need:
        log.error("insufficient demo USDT: have %.2f, need ~%.2f. Fund the demo wallet.",
                  info["usdt_balance"], need)
        return 3
    if base_url == MAINNET_BASE:
        log.warning("MAINNET selected — real funds at risk.")

    # 2) best-effort isolated margin so margin top-ups are possible
    try:
        venue._request("POST", "/v5/position/switch-isolated", {
            "category": "linear", "symbol": symbol, "tradeMode": 1,
            "buyLeverage": f"{leverage}", "sellLeverage": f"{leverage}",
        }, auth=True)
        log.info("perp symbol set to ISOLATED margin @ %gx", leverage)
    except Exception as exc:  # noqa: BLE001 — fall back to cross + unwind backstop
        log.warning("could not set isolated margin (%s); relying on near-liq unwind", str(exc)[:80])

    # 3) open the carry (REAL demo orders)
    bot = CarryBot(venue, CarryBotConfig(notional=notional, leverage=leverage))
    for a in bot.open():
        log.info("OPEN: %s", a)

    # 4) monitor loop — resilient: transient errors never crash the process;
    #    a sustained error streak triggers a safe unwind.
    t0 = time.time()
    errors = 0
    max_consec_errors = 10
    try:
        while bot.state == "HOLD":
            time.sleep(poll_seconds)
            try:
                for a in bot.step():
                    log.info("ACT: %s", a)
                log.info("status: price=%.6g perp_qty=%.6g spot_qty=%.6g margin_ratio=%.3f equity=%.4f",
                         venue.mark_price(), venue.perp_short_qty(), venue.spot_base_qty(),
                         venue.perp_margin_ratio(), venue.equity())
                errors = 0
            except Exception as exc:  # noqa: BLE001 — survive transient venue/network errors
                errors += 1
                log.warning("tick error %d/%d: %s", errors, max_consec_errors, str(exc)[:120])
                if errors >= max_consec_errors:
                    log.error("error streak -> safe unwind")
                    try:
                        for a in bot.unwind("error-streak"):
                            log.info("ACT: %s", a)
                    except Exception as exc2:  # noqa: BLE001
                        log.error("unwind failed (manual check needed): %s", str(exc2)[:120])
                    break
                time.sleep(min(poll_seconds * errors, 120))
                continue
            if max_minutes and (time.time() - t0) / 60.0 >= max_minutes:
                log.info("max-minutes reached -> unwinding")
                for a in bot.unwind("max-minutes"):
                    log.info("ACT: %s", a)
                break
    except KeyboardInterrupt:
        log.info("manual stop -> unwinding")
        for a in bot.unwind("manual stop"):
            log.info("ACT: %s", a)
    log.info("DONE state=%s", bot.state)
    return 0


def _env_float(name: str, default):
    val = os.environ.get(name)
    return float(val) if val not in (None, "") else default


def main() -> int:
    ap = argparse.ArgumentParser()
    # defaults come from env so a server `.env` configures everything
    ap.add_argument("--symbol", default=os.environ.get("CARRY_SYMBOL", "BTCUSDT"))
    ap.add_argument("--notional", type=float, default=_env_float("CARRY_NOTIONAL", 20.0),
                    help="USDT per leg")
    ap.add_argument("--leverage", type=float, default=_env_float("CARRY_LEVERAGE", 1.0))
    ap.add_argument("--poll-seconds", type=float, default=_env_float("CARRY_POLL", 30.0))
    ap.add_argument("--max-minutes", type=float, default=_env_float("CARRY_MAX_MINUTES", None),
                    help="auto-unwind after this many minutes (optional)")
    ap.add_argument("--mainnet", action="store_true", help="use mainnet (real funds)")
    ap.add_argument("--yes-mainnet", action="store_true", help="confirm mainnet")
    args = ap.parse_args()

    base = DEMO_BASE
    if args.mainnet:
        if not args.yes_mainnet:
            print("Refusing mainnet without --yes-mainnet. Demo is the default; drop --mainnet.")
            return 2
        base = MAINNET_BASE
    return run_live(args.symbol, args.notional, args.leverage,
                    args.poll_seconds, base, args.max_minutes)


if __name__ == "__main__":
    raise SystemExit(main())
