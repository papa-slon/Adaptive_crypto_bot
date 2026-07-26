"""Tests for the carry bot: neutral open, funding collection, margin defence,
the drawdown kill-switch, and the safety fixes (transactional open, owned-only
selling, full rebalance, leverage-aware margin floor). All offline.
"""
from __future__ import annotations

import pytest

from algo_engine.carry_bot.bot import CarryBot, CarryBotConfig
from algo_engine.carry_bot.venue import PaperVenue


def test_open_is_delta_neutral():
    v = PaperVenue(price=100.0, cash=2.0, taker_fee=0.0)
    bot = CarryBot(v, CarryBotConfig(notional=1.0, leverage=1.0))
    bot.open()
    assert abs(v.spot_base_qty() - v.perp_short_qty()) < 1e-9
    assert bot.state == "HOLD"
    assert bot.start_equity_snapshot is not None      # dashboard P&L has a baseline


def test_price_move_keeps_equity_flat_ex_funding():
    # no funding, no fees: a delta-neutral book's equity is ~unchanged by price
    v = PaperVenue(price=100.0, cash=2.0, taker_fee=0.0)
    bot = CarryBot(v, CarryBotConfig(notional=1.0, leverage=1.0))
    bot.open()
    eq0 = v.equity()
    for px in (110.0, 95.0, 130.0, 80.0):
        v.set_price(px)
        bot.step()
        assert abs(v.equity() - eq0) < 1e-6, (px, v.equity())   # tight: exact neutrality


def test_collects_positive_funding():
    v = PaperVenue(price=100.0, cash=2.0, taker_fee=0.0)
    bot = CarryBot(v, CarryBotConfig(notional=1.0, leverage=1.0))
    bot.open()
    eq0 = v.equity()
    for _ in range(10):
        v.apply_funding(0.0003)   # positive funding -> the short receives
        bot.step()
    assert v.funding_collected > 0
    assert v.equity() > eq0


def test_margin_topup_then_safe_unwind_on_rally():
    # 5x, price rips up -> the short loses margin -> defended, then unwound safely
    v = PaperVenue(price=100.0, cash=5.0, taker_fee=0.0)
    bot = CarryBot(v, CarryBotConfig(notional=1.0, leverage=5.0, maint_ratio=0.05))
    bot.open()
    acts = []
    # walk the price up in steps fine enough to pass through the top-up band
    # (at 5x it sits between roughly +9% and +14% adverse) before liquidation
    for px in (104.0, 108.0, 110.0, 113.0, 116.0, 122.0, 130.0, 145.0, 160.0):
        v.set_price(px)
        acts += bot.step()
    assert any("TOP-UP" in a for a in acts), acts
    assert bot.state == "FLAT"
    assert any("UNWOUND" in a for a in acts), acts


def test_dd_killswitch_unwinds():
    v = PaperVenue(price=100.0, cash=2.0, taker_fee=0.0)
    bot = CarryBot(v, CarryBotConfig(notional=1.0, leverage=1.0, dd_kill=0.10))
    bot.open()
    fired = False
    for _ in range(50):
        v.apply_funding(-0.01)          # negative funding -> our short PAYS
        acts = bot.step()
        if any("dd-kill" in a for a in acts):
            fired = True
            break
    assert fired, "kill-switch never fired"
    assert bot.state == "FLAT"


# ---------------------------------------------------------------- safety fixes

class _PerpRejectsVenue(PaperVenue):
    """Venue whose perp leg always rejects — models an exchange minimum-size
    rejection, the failure that previously stranded an unhedged spot leg."""

    def open_short_perp(self, notional, leverage):
        raise RuntimeError("order qty invalid: below minOrderQty")


def test_open_rolls_back_spot_when_perp_leg_fails():
    v = _PerpRejectsVenue(price=100.0, cash=2.0, taker_fee=0.0)
    bot = CarryBot(v, CarryBotConfig(notional=1.0, leverage=1.0))
    with pytest.raises(RuntimeError):
        bot.open()
    # the critical invariant: no naked spot position is left behind
    assert v.spot_base_qty() == 0.0, "spot leg was left unhedged after a perp rejection"
    assert bot.state == "FLAT"


def test_unwind_only_sells_what_the_bot_bought():
    v = PaperVenue(price=100.0, cash=5.0, taker_fee=0.0)
    bot = CarryBot(v, CarryBotConfig(notional=1.0, leverage=1.0))
    bot.open()
    bought = v.spot_base_qty()
    bot.unwind("test")
    # PaperVenue tracks only bot-owned coins; the invariant is that we sold
    # exactly what we bought and nothing more
    assert v.spot_base_qty() == pytest.approx(0.0, abs=1e-12)
    assert bought > 0


def test_rebalance_corrects_the_whole_drift_in_one_tick():
    v = PaperVenue(price=100.0, cash=5.0, taker_fee=0.0)
    bot = CarryBot(v, CarryBotConfig(notional=1.0, leverage=1.0, rebalance_delta=0.01))
    bot.open()
    v.base_qty *= 1.20                 # force a 20% long skew
    assert abs(bot._delta()) > 0.1
    bot.step()
    assert abs(bot._delta()) < 1e-9, f"delta not fully corrected: {bot._delta()}"


def test_margin_floor_scales_with_leverage():
    """An absolute floor would fire instantly at high leverage (posted margin is
    1/L); the floor must be relative so 10x does not self-deleverage on tick 1."""
    for lev in (1.0, 3.0, 5.0, 10.0):
        v = PaperVenue(price=100.0, cash=9.0, taker_fee=0.0)
        bot = CarryBot(v, CarryBotConfig(notional=1.0, leverage=lev))
        bot.open()
        acts = bot.step()               # nothing moved -> no defensive action expected
        assert not any("TOP-UP" in a for a in acts), (lev, acts)
        assert bot._margin_floor() > bot.cfg.maint_ratio


def test_adopt_resumes_existing_position_without_buying_more():
    """A restarted container must manage the position it already has."""
    v = PaperVenue(price=100.0, cash=5.0, taker_fee=0.0)
    seeded = CarryBot(v, CarryBotConfig(notional=1.0, leverage=1.0))
    seeded.open()
    spot_before, perp_before = v.spot_base_qty(), v.perp_short_qty()

    fresh = CarryBot(v, CarryBotConfig(notional=1.0, leverage=1.0))
    acts = fresh.adopt()
    assert fresh.state == "HOLD" and acts
    assert v.spot_base_qty() == spot_before and v.perp_short_qty() == perp_before


def test_live_requires_keys(monkeypatch):
    from algo_engine.carry_bot.live import run_live
    for var in ("BYBIT_API_KEY", "BYBIT_API_SECRET", "EXCHANGE_API_KEY", "EXCHANGE_API_SECRET"):
        monkeypatch.delenv(var, raising=False)
    assert run_live("BTCUSDT", 20.0, 1.0, 30.0, "bybit-demo") == 2
