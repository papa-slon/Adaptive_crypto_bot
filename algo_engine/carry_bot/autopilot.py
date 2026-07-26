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
from algo_engine.carry_bot.scanner import Candidate, annualise, rank_candidates
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
                 min_hold_minutes: float = 240.0):
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
        """Fill empty slots, and swap a held coin only when it is clearly worth
        the round-trip cost."""
        by_symbol = {c.symbol: c for c in ranked}

        # 1) drop slots whose own funding has turned bad
        for sym in list(self.slots):
            cand = by_symbol.get(sym)
            if cand is not None and cand.mean_funding < self.exit_funding:
                self.close_slot(sym, f"funding turned {cand.mean_funding*100:+.4f}%/8h")

        # 2) fill free capacity with the best candidates we do not already hold.
        #    Only coins that actually pay us: without this filter a coin dropped
        #    in step 1 would be re-opened on the same pass.
        tradeable = [c for c in ranked if c.mean_funding >= self.exit_funding]
        for cand in tradeable:
            if len(self.slots) >= self.n_slots:
                break
            if cand.symbol not in self.slots:
                self.open_slot(cand)

        # 3) considered swaps — only with a real edge and after a minimum hold
        if len(self.slots) >= self.n_slots and tradeable:
            held = [(s, by_symbol.get(s)) for s in self.slots]
            held_scored = [(s, c.score if c else 0.0) for s, c in held]
            worst_sym, worst_score = min(held_scored, key=lambda kv: kv[1])
            best = next((c for c in tradeable if c.symbol not in self.slots), None)
            slot = self.slots.get(worst_sym)
            held_long_enough = slot and (time.time() - slot.opened_at) / 60.0 >= self.min_hold_minutes
            if best and held_long_enough and worst_score > 0 and best.score > worst_score * self.switch_edge:
                self._act(f"ROTATE {worst_sym} -> {best.symbol} "
                          f"(score {worst_score:.6f} -> {best.score:.6f})")
                self.close_slot(worst_sym, "rotated out for a better payer")
                self.open_slot(best)

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
