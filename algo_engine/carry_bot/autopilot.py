"""Autopilot: run several delta-neutral carry slots and pick the coins itself.

The operator sets capital and how many slots to run; the bot does the rest —
it scans the venue's funding rates, ranks them with the same
`scanner.rank_candidates` used in the backtest, opens a carry on the best
coins, and rotates when something clearly better appears.

Anti-churn is a first-class concern: an earlier experiment proved that
toggling carries on every funding wobble is a FEE TRAP that turns a positive
edge negative. So a held slot is only replaced when

  * its own funding has actually gone bad (below `exit_funding`), AND
  * a candidate is `switch_edge` times better than what we hold,

and every rotation is logged with the reason.

Safety rails are per-slot and identical to the single-symbol runner: preflight
against the instrument's real limits, transactional open with rollback,
leverage-aware margin defence, drawdown kill-switch, and adopt-on-restart.
"""
from __future__ import annotations

import argparse
import logging
import os
import time
from collections import deque

from algo_engine.carry_bot.bot import CarryBot, CarryBotConfig
from algo_engine.carry_bot.scanner import Candidate, decide_rotation, rank_candidates
from algo_engine.carry_bot.state import PortfolioStateWriter, build_portfolio_snapshot
from algo_engine.carry_bot.venues import PreflightError, build_venue, venue_choices

LOG_PATH = "logs/carry_bot.log"


def _logger() -> logging.Logger:
    os.makedirs("logs", exist_ok=True)
    lg = logging.getLogger("carry_autopilot")
    lg.setLevel(logging.INFO)
    if not lg.handlers:
        fmt = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
        fh = logging.FileHandler(LOG_PATH, encoding="utf-8"); fh.setFormatter(fmt)
        sh = logging.StreamHandler(); sh.setFormatter(fmt)
        lg.addHandler(fh); lg.addHandler(sh)
    return lg


class Slot:
    """One carry position: its own venue handle (venues are symbol-scoped)."""

    def __init__(self, symbol: str, venue, bot: CarryBot, candidate: Candidate | None):
        self.symbol = symbol
        self.venue = venue
        self.bot = bot
        self.candidate = candidate
        self.opened_at = time.time()

    @property
    def alive(self) -> bool:
        return self.bot.state == "HOLD"


class Autopilot:
    def __init__(self, venue_name: str, keys: tuple[str, str], capital: float,
                 slots: int, leverage: float, log: logging.Logger,
                 exit_funding: float = 0.0, switch_edge: float = 1.4,
                 # rotation costs ~0.3% of notional (4 taker fills), so the
                 # minimum hold is measured in DAYS, not hours
                 min_hold_minutes: float = 4320.0):
        self.venue_name = venue_name
        self.keys = keys
        self.capital = capital
        self.n_slots = slots
        self.leverage = leverage
        self.log = log
        self.exit_funding = exit_funding
        self.switch_edge = switch_edge
        self.min_hold_minutes = min_hold_minutes
        self.slots: dict[str, Slot] = {}
        self.actions: deque = deque(maxlen=60)

    # capital per slot -> tradeable notional (the rest is perp margin)
    def slot_notional(self) -> float:
        per_slot = self.capital / max(self.n_slots, 1)
        return per_slot / (1.0 + 1.0 / max(self.leverage, 1e-9))

    def _act(self, msg: str) -> None:
        self.log.info("ACT: %s", msg)
        self.actions.appendleft(msg)

    def scan(self, top_n: int) -> list[Candidate]:
        """Rank the venue's perps by current funding (liquidity-filtered)."""
        from algo_engine.carry_bot.scanner import scan_bybit_live
        if self.venue_name.startswith("bybit"):
            return scan_bybit_live(top_n=top_n)
        # BingX (and anything else): use the venue's own funding endpoint if it
        # exposes one; otherwise keep whatever we hold rather than guess.
        probe = build_venue(self.venue_name, *self.keys, symbol="BTC-USDT")
        scan = getattr(probe, "scan_funding", None)
        if callable(scan):
            stats = scan()
            return rank_candidates(stats, top_n=top_n, min_obs=1)
        self.log.warning("no scanner for venue %s — holding current slots", self.venue_name)
        return []

    def open_slot(self, cand: Candidate) -> bool:
        notional = self.slot_notional()
        try:
            venue = build_venue(self.venue_name, *self.keys, symbol=cand.symbol,
                                enable_trading=True, leverage=self.leverage)
            venue.preflight(notional, self.leverage)
            try:
                venue.ensure_isolated(self.leverage)
            except Exception as exc:  # noqa: BLE001 — cross margin still has the unwind backstop
                self.log.warning("%s: isolated margin unavailable (%s)", cand.symbol, str(exc)[:80])
            bot = CarryBot(venue, CarryBotConfig(notional=notional, leverage=self.leverage))
            existing = venue.adopt_existing()
            acts = bot.adopt() if existing.get("perp_qty", 0) > 0 else bot.open()
            for a in acts:
                self._act(f"[{cand.symbol}] {a}")
            self.slots[cand.symbol] = Slot(cand.symbol, venue, bot, cand)
            self._act(f"[{cand.symbol}] slot live — funding {cand.mean_funding*100:+.4f}%/8h "
                      f"(~{cand.ann_pct:+.1f}%/yr)")
            return True
        except PreflightError as exc:
            self.log.warning("skip %s: %s", cand.symbol, str(exc)[:160])
        except Exception as exc:  # noqa: BLE001 — one bad symbol must not stop the fleet
            self.log.error("could not open %s: %s", cand.symbol, str(exc)[:160])
        return False

    def close_slot(self, symbol: str, reason: str) -> None:
        slot = self.slots.get(symbol)
        if not slot:
            return
        try:
            for a in slot.bot.unwind(reason):
                self._act(f"[{symbol}] {a}")
        except Exception as exc:  # noqa: BLE001
            self.log.error("[%s] unwind FAILED (manual check needed): %s", symbol, str(exc)[:160])
        self.slots.pop(symbol, None)

    def rotate(self, ranked: list[Candidate]) -> None:
        """Apply the shared rotation policy — the SAME pure decision function
        the historical backtest runs, so measured behaviour equals live
        behaviour."""
        now = time.time()
        held_minutes = {s: (now - slot.opened_at) / 60.0 for s, slot in self.slots.items()}
        to_close, to_open = decide_rotation(
            held=list(self.slots),
            ranked=ranked,
            n_slots=self.n_slots,
            held_minutes=held_minutes,
            exit_funding=self.exit_funding,
            switch_edge=self.switch_edge,
            min_hold_minutes=self.min_hold_minutes,
        )
        for sym in to_close:
            self.close_slot(sym, "rotation policy")
        for cand in to_open:
            self.open_slot(cand)

    def step_all(self) -> None:
        for sym in list(self.slots):
            slot = self.slots[sym]
            try:
                for a in slot.bot.step():
                    self._act(f"[{sym}] {a}")
                try:
                    slot.venue.refresh_funding()
                except Exception:  # noqa: BLE001 — display only
                    pass
                if not slot.alive:      # the bot unwound itself (kill-switch / margin)
                    self.slots.pop(sym, None)
            except Exception as exc:  # noqa: BLE001 — one slot's error must not kill the fleet
                self.log.warning("[%s] tick error: %s", sym, str(exc)[:150])

    def unwind_all(self, reason: str) -> None:
        for sym in list(self.slots):
            self.close_slot(sym, reason)


def resolve_keys(venue_name: str) -> tuple[str, str] | None:
    prefix = "BYBIT" if venue_name.startswith("bybit") else "BINGX"
    k = os.environ.get(f"{prefix}_API_KEY") or os.environ.get("EXCHANGE_API_KEY")
    s = os.environ.get(f"{prefix}_API_SECRET") or os.environ.get("EXCHANGE_API_SECRET")
    return (k, s) if k and s else None


def _env(name: str, default):
    v = os.environ.get(name)
    return type(default)(v) if v not in (None, "") else default


def main() -> int:
    ap = argparse.ArgumentParser(description="Hands-off multi-coin funding carry")
    ap.add_argument("--venue", default=os.environ.get("CARRY_VENUE", "bybit-demo"),
                    choices=venue_choices())
    ap.add_argument("--capital", type=float, default=_env("CARRY_CAPITAL", 200.0),
                    help="total USDT the bot may deploy across all slots")
    ap.add_argument("--slots", type=int, default=_env("CARRY_SLOTS", 3))
    ap.add_argument("--leverage", type=float, default=_env("CARRY_LEVERAGE", 1.0))
    ap.add_argument("--poll-seconds", type=float, default=_env("CARRY_POLL", 30.0))
    ap.add_argument("--rescan-minutes", type=float, default=_env("CARRY_RESCAN_MIN", 60.0))
    ap.add_argument("--yes-mainnet", action="store_true")
    args = ap.parse_args()

    if ("demo" not in args.venue and "test" not in args.venue) and not args.yes_mainnet:
        print(f"Refusing real-money venue '{args.venue}' without --yes-mainnet.")
        return 2
    keys = resolve_keys(args.venue)
    if not keys:
        prefix = "BYBIT" if args.venue.startswith("bybit") else "BINGX"
        print(f"set {prefix}_API_KEY and {prefix}_API_SECRET in your environment.")
        return 2

    log = _logger()
    pilot = Autopilot(args.venue, keys, args.capital, args.slots, args.leverage, log)
    writer = PortfolioStateWriter()
    started = time.time()
    log.info("AUTOPILOT start: venue=%s capital=%.2f slots=%d leverage=%gx "
             "-> notional/slot=%.2f", args.venue, args.capital, args.slots,
             args.leverage, pilot.slot_notional())

    def persist():
        try:
            writer.update(build_portfolio_snapshot(pilot, args, started))
        except Exception as exc:  # noqa: BLE001 — dashboard must never break trading
            log.warning("state write failed: %s", str(exc)[:100])

    last_scan = 0.0
    try:
        while True:
            now = time.time()
            if now - last_scan >= args.rescan_minutes * 60.0:
                try:
                    ranked = pilot.scan(top_n=max(args.slots * 3, 6))
                    if ranked:
                        log.info("scan: " + ", ".join(
                            f"{c.symbol} {c.mean_funding*100:+.4f}%/8h (~{c.ann_pct:+.0f}%/yr)"
                            for c in ranked[:6]))
                        pilot.rotate(ranked)
                except Exception as exc:  # noqa: BLE001 — a failed scan just means "hold"
                    log.warning("scan failed: %s", str(exc)[:150])
                last_scan = now
            pilot.step_all()
            persist()
            time.sleep(args.poll_seconds)
    except KeyboardInterrupt:
        log.info("manual stop -> unwinding every slot")
        pilot.unwind_all("manual stop")
        persist()
    log.info("AUTOPILOT stopped")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
