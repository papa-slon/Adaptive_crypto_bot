"""Live carry-bot loop (real orders on a demo/paper-money account).

Flow:
  1. read API keys from env,
  2. connectivity + balance check,
  3. PREFLIGHT: verify both legs are tradeable at this size (instrument lot
     size / min order qty / min notional) BEFORE anything is sent — a rejected
     second leg must never strand an unhedged first leg,
  4. if a position already exists on the venue (e.g. the container restarted),
     ADOPT it instead of opening a second one,
  5. otherwise OPEN the carry transactionally, then poll every `poll_seconds`:
     defend perp margin / keep delta neutral / dd kill-switch, refresh the
     funding actually booked by the exchange, and persist state for the
     dashboard,
  6. Ctrl-C, kill-switch, error streak or max-minutes -> clean unwind.

Defaults to a DEMO endpoint. Mainnet requires explicit --mainnet AND
--yes-mainnet. Validate on demo with small size at 1x first.
"""
from __future__ import annotations

import argparse
import logging
import os
import time
from collections import deque

from algo_engine.carry_bot.bot import CarryBot, CarryBotConfig
from algo_engine.carry_bot.venues import PreflightError, build_venue, venue_choices

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


def resolve_keys(venue_name: str) -> tuple[str, str] | None:
    """Venue-specific keys, falling back to generic EXCHANGE_API_* names."""
    prefix = "BYBIT" if venue_name.startswith("bybit") else "BINGX"
    k = os.environ.get(f"{prefix}_API_KEY") or os.environ.get("EXCHANGE_API_KEY")
    s = os.environ.get(f"{prefix}_API_SECRET") or os.environ.get("EXCHANGE_API_SECRET")
    return (k, s) if k and s else None


def run_live(symbol: str, notional: float, leverage: float, poll_seconds: float,
             venue_name: str = "bybit-demo", max_minutes: float | None = None) -> int:
    keys = resolve_keys(venue_name)
    if not keys:
        prefix = "BYBIT" if venue_name.startswith("bybit") else "BINGX"
        print(f"set {prefix}_API_KEY and {prefix}_API_SECRET in your environment.")
        return 2
    log = _logger()
    venue = build_venue(venue_name, *keys, symbol=symbol, enable_trading=True, leverage=leverage)

    # 1) connectivity + funding check (no orders yet)
    info = venue.connectivity_check()
    need = notional + notional / max(leverage, 1.0)     # spot leg + perp margin
    log.info("venue=%s %s mark=%s USDT=%.2f need~%.2f",
             info.get("base_url", venue_name), symbol, info["mark_price"],
             info["usdt_balance"], need)
    if info["usdt_balance"] < need:
        log.error("insufficient balance: have %.2f, need ~%.2f. Fund the account.",
                  info["usdt_balance"], need)
        return 3
    if "demo" not in venue_name and "test" not in venue_name:
        log.warning("NON-DEMO endpoint selected — real funds at risk.")

    # 2) PREFLIGHT — both legs must be tradeable at this size
    try:
        pf = venue.preflight(notional, leverage)
        log.info("preflight OK: price=%.6g spot_step=%s perp_step=%s",
                 pf["price"], pf["spot"]["qty_step"], pf["linear"]["qty_step"])
    except PreflightError as exc:
        log.error("PREFLIGHT FAILED — refusing to trade: %s", exc)
        return 4

    # 3) best-effort isolated margin so margin top-ups are possible
    try:
        venue.ensure_isolated(leverage)
        log.info("perp symbol set to ISOLATED margin @ %gx", leverage)
    except Exception as exc:  # noqa: BLE001 — fall back to cross + unwind backstop
        log.warning("could not set isolated margin (%s); relying on near-liq unwind", str(exc)[:100])

    bot = CarryBot(venue, CarryBotConfig(notional=notional, leverage=leverage))
    actions: deque = deque(maxlen=40)
    from algo_engine.carry_bot.state import StateWriter, build_snapshot
    writer = StateWriter()
    meta = {"mode": venue_name, "symbol": symbol, "notional": notional, "leverage": leverage}
    t0 = time.time()
    errors = 0
    max_consec_errors = 10

    def persist():
        try:
            writer.update(build_snapshot(venue, bot, meta, actions, errors, t0))
        except Exception as exc:  # noqa: BLE001 — dashboard write must never break trading
            log.warning("state write failed: %s", str(exc)[:100])

    # 4) adopt an existing position (restart-safe) or open a new one
    try:
        existing = venue.adopt_existing()
        if existing.get("perp_qty", 0) > 0:
            for a in bot.adopt():
                log.info("ADOPT: %s", a); actions.appendleft(a)
        else:
            for a in bot.open():
                log.info("OPEN: %s", a); actions.appendleft(a)
    except Exception as exc:  # noqa: BLE001
        log.error("could not establish the carry (both legs rolled back if needed): %s", str(exc)[:200])
        persist()
        return 5

    persist()

    # 5) monitor loop — transient errors never crash the process
    try:
        while bot.state == "HOLD":
            time.sleep(poll_seconds)
            try:
                for a in bot.step():
                    log.info("ACT: %s", a); actions.appendleft(a)
                try:
                    venue.refresh_funding()
                except Exception:  # noqa: BLE001 — funding display is not critical
                    pass
                log.info("status: price=%.6g perp_qty=%.6g spot_qty=%.6g margin_ratio=%.3f "
                         "equity=%.4f funding=%.4f",
                         venue.mark_price(), venue.perp_short_qty(), venue.spot_base_qty(),
                         venue.perp_margin_ratio(), venue.equity(),
                         getattr(venue, "funding_collected", 0.0))
                errors = 0
                persist()
            except Exception as exc:  # noqa: BLE001 — survive transient venue/network errors
                errors += 1
                log.warning("tick error %d/%d: %s", errors, max_consec_errors, str(exc)[:150])
                persist()
                if errors >= max_consec_errors:
                    log.error("error streak -> safe unwind")
                    try:
                        for a in bot.unwind("error-streak"):
                            log.info("ACT: %s", a); actions.appendleft(a)
                    except Exception as exc2:  # noqa: BLE001
                        log.error("unwind failed (MANUAL CHECK NEEDED): %s", str(exc2)[:150])
                    break
                time.sleep(min(poll_seconds * errors, 120))
                continue
            if max_minutes and (time.time() - t0) / 60.0 >= max_minutes:
                log.info("max-minutes reached -> unwinding")
                for a in bot.unwind("max-minutes"):
                    log.info("ACT: %s", a); actions.appendleft(a)
                break
    except KeyboardInterrupt:
        log.info("manual stop -> unwinding")
        for a in bot.unwind("manual stop"):
            log.info("ACT: %s", a); actions.appendleft(a)
    persist()
    log.info("DONE state=%s", bot.state)
    return 0


def _env_float(name: str, default):
    val = os.environ.get(name)
    return float(val) if val not in (None, "") else default


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbol", default=os.environ.get("CARRY_SYMBOL", "BTCUSDT"))
    ap.add_argument("--notional", type=float, default=_env_float("CARRY_NOTIONAL", 20.0),
                    help="USDT per leg")
    ap.add_argument("--leverage", type=float, default=_env_float("CARRY_LEVERAGE", 1.0))
    ap.add_argument("--poll-seconds", type=float, default=_env_float("CARRY_POLL", 30.0))
    ap.add_argument("--max-minutes", type=float, default=_env_float("CARRY_MAX_MINUTES", None))
    ap.add_argument("--venue", default=os.environ.get("CARRY_VENUE", "bybit-demo"),
                    choices=venue_choices(),
                    help="exchange endpoint (demo endpoints are the safe default)")
    ap.add_argument("--yes-mainnet", action="store_true",
                    help="required confirmation when --venue is a real-money endpoint")
    args = ap.parse_args()

    if ("demo" not in args.venue and "test" not in args.venue) and not args.yes_mainnet:
        print(f"Refusing real-money venue '{args.venue}' without --yes-mainnet. "
              f"Use a demo venue: {', '.join(v for v in venue_choices() if 'demo' in v or 'test' in v)}")
        return 2
    return run_live(args.symbol, args.notional, args.leverage,
                    args.poll_seconds, args.venue, args.max_minutes)


if __name__ == "__main__":
    raise SystemExit(main())
