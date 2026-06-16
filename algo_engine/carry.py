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


def simulate_carry(spot: pd.Series, perp: pd.Series, funding_bar: np.ndarray,
                   cfg: CarryConfig, bars_per_year: float) -> dict:
    n = min(len(spot), len(perp), len(funding_bar))
    spot = spot.iloc[:n].to_numpy(dtype=float)
    perp = perp.iloc[:n].to_numpy(dtype=float)
    fb = np.asarray(funding_bar[:n], dtype=float)
    leg_cost = cfg.fee + cfg.slippage           # per leg, per side

    equity = 1.0                # capital = spot notional (1x, conservative)
    funding_total = 0.0
    basis_total = 0.0
    n_funding = 0
    toggles = 0
    in_carry = False
    s0 = p0 = 0.0
    cur_funding = 0.0
    eq_curve = []

    def open_carry(i):
        nonlocal in_carry, s0, p0, equity, toggles
        in_carry = True; s0 = spot[i]; p0 = perp[i]
        equity -= 2 * leg_cost          # entry: both legs
        toggles += 1

    def close_carry(i):
        nonlocal in_carry, equity
        in_carry = False
        equity -= 2 * leg_cost          # exit: both legs

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
                # realise current basis into equity, then go flat
                basis = (spot[i] / s0 - 1.0) - (perp[i] / p0 - 1.0)
                equity += basis; basis_total += basis
                close_carry(i)

        # funding accrues to the SHORT perp leg while in carry
        if in_carry and rate != 0.0:
            funding_total += rate; equity += rate; n_funding += 1

        # mark-to-market for the curve (basis is unrealised while held)
        if in_carry:
            basis_now = (spot[i] / s0 - 1.0) - (perp[i] / p0 - 1.0)
            eq_curve.append(equity + basis_now)
        else:
            eq_curve.append(equity)

    # close at the end
    if in_carry:
        basis = (spot[-1] / s0 - 1.0) - (perp[-1] / p0 - 1.0)
        equity += basis; basis_total += basis
        close_carry(n - 1)
    total_return = equity - 1.0
    years = n / bars_per_year if bars_per_year else 0.0
    annualized = ((1 + total_return) ** (1 / years) - 1) if years > 0 and total_return > -1 else 0.0
    return {
        "total_return": total_return,
        "annualized": annualized,
        "funding_total": funding_total,
        "basis_total": basis_total,
        "n_funding": n_funding,
        "toggles": toggles,
        "max_drawdown": metrics.max_drawdown(pd.Series(eq_curve)) if eq_curve else 0.0,
        "years": years,
    }
