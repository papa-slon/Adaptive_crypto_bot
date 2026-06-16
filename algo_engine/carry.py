"""Delta-neutral cash-and-carry simulator: LONG spot + SHORT perp, same notional.

Price risk ~cancels (spot and perp move together); income = funding collected
by the short perp leg every 8h when funding is positive. This is the only
construct in this repo with a real positive expectancy — but it is a CARRY
trade (hold-and-collect), not minute scalping, and yields are modest.

Two modes:
  * static : enter once, hold the whole window, collect funding throughout.
  * timed  : only hold the carry while funding is positive (don't pay funding
             in negative regimes); sit flat otherwise. Costs fees on each toggle.

Look-ahead free; fees+slippage charged on BOTH legs at entry and exit.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from . import metrics


@dataclass
class CarryConfig:
    fee: float = 0.0004        # taker per side per leg (spot+perp legs each pay)
    slippage: float = 0.0002
    timed: bool = False        # only hold carry while funding > enter_thr
    enter_thr: float = 0.0     # funding rate threshold to be in the carry (timed mode)
    leverage: float = 1.0      # notional multiple vs capital (scales yield AND risk)
    maint_margin: float = 0.9  # perp leg liquidates if its adverse move x L exceeds this


def simulate_carry(spot: pd.Series, perp: pd.Series, funding_bar: np.ndarray,
                   cfg: CarryConfig, bars_per_year: float) -> dict:
    n = min(len(spot), len(perp), len(funding_bar))
    spot = spot.iloc[:n].to_numpy(dtype=float)
    perp = perp.iloc[:n].to_numpy(dtype=float)
    fb = np.asarray(funding_bar[:n], dtype=float)
    leg_cost = cfg.fee + cfg.slippage           # per leg, per side
    L = cfg.leverage

    equity = 1.0                # capital; carry runs at L x this notional
    funding_total = 0.0
    basis_total = 0.0
    n_funding = 0
    toggles = 0
    in_carry = False
    s0 = p0 = 0.0
    cur_funding = 0.0
    max_adverse_perp = 0.0      # worst (perp up) excursion while holding -> liquidation risk
    eq_curve = []

    def open_carry(i):
        nonlocal in_carry, s0, p0, equity, toggles
        in_carry = True; s0 = spot[i]; p0 = perp[i]
        equity -= 2 * leg_cost * L       # entry: both legs, at L notional
        toggles += 1

    def close_carry(i):
        nonlocal in_carry, equity
        in_carry = False
        equity -= 2 * leg_cost * L       # exit: both legs

    for i in range(n):
        rate = fb[i]
        if rate != 0.0:
            cur_funding = rate
        # decide membership
        if not cfg.timed:
            if not in_carry and i == 0:
                open_carry(i)
        else:
            want = cur_funding > cfg.enter_thr
            if want and not in_carry:
                open_carry(i)
            elif not want and in_carry:
                basis = (spot[i] / s0 - 1.0) - (perp[i] / p0 - 1.0)
                equity += basis * L; basis_total += basis * L
                close_carry(i)

        # funding accrues to the SHORT perp leg while in carry (scaled by L)
        if in_carry and rate != 0.0:
            funding_total += rate * L; equity += rate * L; n_funding += 1

        # track perp-leg liquidation distance (short loses when perp rises)
        if in_carry:
            adverse = perp[i] / p0 - 1.0
            max_adverse_perp = max(max_adverse_perp, adverse)
            basis_now = (spot[i] / s0 - 1.0) - (perp[i] / p0 - 1.0)
            eq_curve.append(equity + basis_now * L)
        else:
            eq_curve.append(equity)

    if in_carry:
        basis = (spot[-1] / s0 - 1.0) - (perp[-1] / p0 - 1.0)
        equity += basis * L; basis_total += basis * L
        close_carry(n - 1)
    total_return = equity - 1.0
    years = n / bars_per_year if bars_per_year else 0.0
    annualized = ((1 + total_return) ** (1 / years) - 1) if years > 0 and total_return > -1 else 0.0
    # cross-account liquidation: the isolated perp short can be wiped before the
    # offsetting spot gain is realised, even though the position is delta-neutral.
    liquidated = (max_adverse_perp * L) >= cfg.maint_margin
    return {
        "total_return": total_return,
        "annualized": annualized,
        "funding_total": funding_total,
        "basis_total": basis_total,
        "n_funding": n_funding,
        "toggles": toggles,
        "max_drawdown": metrics.max_drawdown(pd.Series(eq_curve)) if eq_curve else 0.0,
        "years": years,
        "max_adverse_perp": max_adverse_perp,
        "liquidated": liquidated,
    }
