"""Delta-neutral funding-carry bot logic (venue-injected, side-effect-light).

Lifecycle:
  FLAT  -> open(): buy spot notional N, short perp notional N at leverage L.
  HOLD  -> on each tick (price, optional funding settlement):
             * collect funding (handled by the venue feed),
             * keep delta ~neutral (rebalance if it drifts past a threshold),
             * defend the perp leg: if its margin ratio nears maintenance,
               top up margin from cash (or de-lever by reducing both legs),
             * kill-switch: if account equity draws down past a limit, unwind.

Every state transition returns a list of human-readable actions so the runner
can log exactly what happened (and so tests can assert on behaviour).
"""
from __future__ import annotations

from dataclasses import dataclass

from .venue import Venue


@dataclass
class CarryBotConfig:
    notional: float = 1.0          # carry size (quote) per leg
    leverage: float = 1.0          # perp leg leverage
    rebalance_delta: float = 0.03  # rebalance when |delta|/notional exceeds this
    margin_floor: float = 0.15     # top up the perp leg if its ratio drops below this
    margin_target: float = 0.30    # ratio to restore to on a top-up
    maint_ratio: float = 0.05      # exchange maintenance (liquidation) ratio
    dd_kill: float = 0.20          # unwind if account equity drops this far from peak


class CarryBot:
    def __init__(self, venue: Venue, cfg: CarryBotConfig):
        self.v = venue
        self.cfg = cfg
        self.state = "FLAT"
        self.peak_equity = venue.equity()
        self.opened = False

    # ---- helpers ----
    def _delta(self) -> float:
        px = self.v.mark_price()
        return self.v.spot_base_qty() * px - self.v.perp_short_qty() * px

    # ---- lifecycle ----
    def open(self) -> list[str]:
        if self.state != "FLAT":
            return []
        self.v.buy_spot(self.cfg.notional)
        self.v.open_short_perp(self.cfg.notional, self.cfg.leverage)
        self.state = "HOLD"
        self.opened = True
        self.peak_equity = self.v.equity()
        return [f"OPEN carry: long spot {self.cfg.notional:.4g} + short perp "
                f"{self.cfg.notional:.4g} @ {self.cfg.leverage:g}x, price={self.v.mark_price():.6g}"]

    def unwind(self, reason: str) -> list[str]:
        acts = []
        if self.v.perp_short_qty() > 0:
            self.v.reduce_short_perp_qty(self.v.perp_short_qty())
            acts.append("CLOSE perp short")
        if self.v.spot_base_qty() > 0:
            self.v.sell_spot_qty(self.v.spot_base_qty())
            acts.append("SELL spot")
        self.state = "FLAT"
        acts.append(f"UNWOUND ({reason}); equity={self.v.equity():.6g}")
        return acts

    def step(self) -> list[str]:
        """Run one monitoring tick. Call after the venue's price/funding feed
        has advanced for this bar."""
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
        if ratio < cfg.margin_floor:
            notional = self.v.perp_short_qty() * self.v.mark_price()
            need = (cfg.margin_target - ratio) * notional
            self.v.add_perp_margin(need)
            acts.append(f"TOP-UP perp margin +{need:.4g} (ratio {ratio:.2f}->~{cfg.margin_target:.2f})")

        # keep delta neutral
        delta = self._delta()
        if cfg.notional > 0 and abs(delta) / cfg.notional > cfg.rebalance_delta:
            px = self.v.mark_price()
            qty = abs(delta) / px / 2.0      # split the correction across both legs
            if delta > 0:                    # too long: sell spot a touch
                self.v.sell_spot_qty(qty)
            else:                            # too short: buy back a little perp
                self.v.reduce_short_perp_qty(qty)
            acts.append(f"REBALANCE delta={delta:+.4g} -> ~0")
        return acts
