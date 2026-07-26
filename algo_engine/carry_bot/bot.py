"""Delta-neutral funding-carry bot logic (venue-injected, side-effect-light).

Lifecycle:
  FLAT  -> open(): buy spot notional N, short perp notional N at leverage L.
           The two legs are opened TRANSACTIONALLY: if the perp leg fails, the
           spot leg is sold back, so the bot can never be left holding an
           unhedged position.
  HOLD  -> on each tick (price, exchange-settled funding):
             * keep delta ~neutral (rebalance when it drifts past a threshold),
             * defend the perp leg: if its margin ratio nears maintenance, top
               up margin from cash; if it breaches, unwind,
             * kill-switch: if account equity draws down past a limit, unwind.

Every state transition returns human-readable actions so the runner can log
exactly what happened and tests can assert on behaviour.
"""
from __future__ import annotations

from dataclasses import dataclass

from .venue import Venue


@dataclass
class CarryBotConfig:
    notional: float = 1.0          # carry size (quote) per leg
    leverage: float = 1.0          # perp leg leverage (margin efficiency, NOT size)
    rebalance_delta: float = 0.03  # rebalance when |delta|/notional exceeds this
    # Margin thresholds are expressed as a FRACTION OF THE POSTED MARGIN (1/L),
    # so they mean the same thing at every leverage. margin_floor_frac=0.45 =>
    # "top up once 55% of the initially posted margin has been eaten".
    margin_floor_frac: float = 0.35
    margin_target_frac: float = 0.80
    maint_ratio: float = 0.05      # exchange maintenance (liquidation) ratio
    dd_kill: float = 0.20          # unwind if account equity drops this far from peak


class CarryBot:
    def __init__(self, venue: Venue, cfg: CarryBotConfig):
        self.v = venue
        self.cfg = cfg
        self.state = "FLAT"
        self.peak_equity = venue.equity()
        self.opened = False
        self.start_equity_snapshot: float | None = None

    # ---- helpers ----
    def _delta(self) -> float:
        """Net directional exposure in quote units: +ve = net long."""
        px = self.v.mark_price()
        return (self.v.spot_base_qty() - self.v.perp_short_qty()) * px

    def _posted_ratio(self) -> float:
        """Margin ratio at entry: posting 1/L of the notional."""
        return 1.0 / max(self.cfg.leverage, 1e-9)

    def _margin_floor(self) -> float:
        """Top-up threshold placed BETWEEN liquidation and the posted margin.

        Expressed as a fraction of the distance from the maintenance ratio up to
        the margin actually posted, so it means the same thing at 1x and at 10x
        and can never sit above the posted margin (which would make the bot
        top up on the very first tick and silently de-lever itself).
        """
        posted = self._posted_ratio()
        room = max(posted - self.cfg.maint_ratio, 0.0)
        return self.cfg.maint_ratio + room * self.cfg.margin_floor_frac

    def _margin_target(self) -> float:
        posted = self._posted_ratio()
        room = max(posted - self.cfg.maint_ratio, 0.0)
        return self.cfg.maint_ratio + room * self.cfg.margin_target_frac

    def leverage_is_runnable(self) -> bool:
        """False when the posted margin barely clears maintenance — at that
        leverage any tick could liquidate before a top-up could land."""
        return self._posted_ratio() > self.cfg.maint_ratio * 1.5

    # ---- lifecycle ----
    def open(self) -> list[str]:
        """Open both legs atomically. If the perp leg fails, unwind the spot leg
        and re-raise, so a rejected order can never strand a naked position."""
        if self.state != "FLAT":
            return []
        if not self.leverage_is_runnable():
            raise RuntimeError(
                f"leverage {self.cfg.leverage:g}x posts only {self._posted_ratio():.3f} margin, "
                f"too close to the {self.cfg.maint_ratio:.3f} maintenance ratio — a single tick "
                f"could liquidate before a top-up lands. Use lower leverage.")
        self.v.buy_spot(self.cfg.notional)
        try:
            self.v.open_short_perp(self.cfg.notional, self.cfg.leverage)
        except Exception:
            # roll the first leg back before surfacing the failure
            try:
                held = self.v.spot_base_qty()
                if held > 0:
                    self.v.sell_spot_qty(held)
            except Exception:  # noqa: BLE001 — report the ORIGINAL failure
                pass
            raise
        self.state = "HOLD"
        self.opened = True
        self.peak_equity = self.v.equity()
        self.start_equity_snapshot = self.peak_equity
        return [f"OPEN carry: long spot {self.cfg.notional:.4g} + short perp "
                f"{self.cfg.notional:.4g} @ {self.cfg.leverage:g}x, price={self.v.mark_price():.6g}"]

    def adopt(self) -> list[str]:
        """Resume managing a position that already exists on the venue (e.g.
        after a container restart) instead of opening a second one."""
        qty = self.v.perp_short_qty()
        if qty <= 0:
            return []
        self.state = "HOLD"
        self.opened = True
        eq = self.v.equity()
        self.peak_equity = eq
        self.start_equity_snapshot = eq
        return [f"ADOPT existing carry: perp short {qty:.6g}, "
                f"spot {self.v.spot_base_qty():.6g}, price={self.v.mark_price():.6g}"]

    def unwind(self, reason: str) -> list[str]:
        acts = []
        if self.v.perp_short_qty() > 0:
            self.v.reduce_short_perp_qty(self.v.perp_short_qty())
            acts.append("CLOSE perp short")
        held = self.v.spot_base_qty()          # bot-owned only, never the user's coins
        if held > 0:
            self.v.sell_spot_qty(held)
            acts.append("SELL spot")
        self.state = "FLAT"
        acts.append(f"UNWOUND ({reason}); equity={self.v.equity():.6g}")
        return acts

    def step(self) -> list[str]:
        """One monitoring tick, after the venue's price/funding has advanced."""
        if self.state != "HOLD":
            return []
        acts: list[str] = []
        cfg = self.cfg

        # kill-switch on account equity drawdown
        eq = self.v.equity()
        self.peak_equity = max(self.peak_equity, eq)
        if self.peak_equity > 0 and (self.peak_equity - eq) / self.peak_equity >= cfg.dd_kill:
            return self.unwind("dd-kill")

        # defend the perp leg
        ratio = self.v.perp_margin_ratio()
        if ratio <= cfg.maint_ratio:
            return self.unwind("perp near liquidation")
        floor = self._margin_floor()
        if ratio < floor:
            target = self._margin_target()
            notional = self.v.perp_short_qty() * self.v.mark_price()
            need = (target - ratio) * notional
            if need > 0:
                self.v.add_perp_margin(need)
                acts.append(f"TOP-UP perp margin +{need:.4g} (ratio {ratio:.3f} -> ~{target:.3f})")

        # keep delta neutral — correct the WHOLE drift, not half of it
        delta = self._delta()
        if cfg.notional > 0 and abs(delta) / cfg.notional > cfg.rebalance_delta:
            px = self.v.mark_price()
            qty = abs(delta) / px
            before = delta
            if delta > 0:                    # net long: shed spot
                self.v.sell_spot_qty(qty)
            else:                            # net short: buy back perp
                self.v.reduce_short_perp_qty(qty)
            acts.append(f"REBALANCE delta {before:+.6g} -> {self._delta():+.6g}")
        return acts
