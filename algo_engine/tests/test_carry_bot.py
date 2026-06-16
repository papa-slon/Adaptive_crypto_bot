"""Tests for the carry bot: neutral open, funding collection, margin defence,
and the drawdown kill-switch — all offline against PaperVenue.
"""
from __future__ import annotations

from algo_engine.carry_bot.bot import CarryBot, CarryBotConfig
from algo_engine.carry_bot.venue import PaperVenue


def test_open_is_delta_neutral():
    v = PaperVenue(price=100.0, cash=2.0, taker_fee=0.0)
    bot = CarryBot(v, CarryBotConfig(notional=1.0, leverage=1.0))
    bot.open()
    # equal base long and perp short notional at the same price
    assert abs(v.spot_base_qty() - v.perp_short_qty()) < 1e-9
    assert bot.state == "HOLD"


def test_price_move_keeps_equity_flat_ex_funding():
    # no funding, no fees: a delta-neutral book's equity is ~unchanged by price
    v = PaperVenue(price=100.0, cash=2.0, taker_fee=0.0)
    bot = CarryBot(v, CarryBotConfig(notional=1.0, leverage=3.0))
    bot.open()
    eq0 = v.equity()
    for px in (110.0, 95.0, 130.0, 80.0):
        v.set_price(px)
        bot.step()
    assert abs(v.equity() - eq0) < 0.02, v.equity()


def test_collects_positive_funding():
    v = PaperVenue(price=100.0, cash=2.0, taker_fee=0.0)
    bot = CarryBot(v, CarryBotConfig(notional=1.0, leverage=1.0))
    bot.open()
    eq0 = v.equity()
    for _ in range(10):
        v.apply_funding(0.0003)   # positive funding -> short receives
        bot.step()
    assert v.funding_collected > 0
    assert v.equity() > eq0


def test_margin_topup_then_liquidation_on_rally():
    # leverage 5x, price rips up -> perp short loses -> margin defended, then killed
    v = PaperVenue(price=100.0, cash=5.0, taker_fee=0.0)
    bot = CarryBot(v, CarryBotConfig(notional=1.0, leverage=5.0,
                                     margin_floor=0.15, maint_ratio=0.05))
    bot.open()
    acts_all = []
    for px in (108.0, 116.0, 125.0, 140.0, 160.0):
        v.set_price(px)
        acts_all += bot.step()
    # it should have tried to defend margin and ultimately unwound safely
    assert any("TOP-UP" in a for a in acts_all), acts_all
    assert bot.state == "FLAT"
    assert any("UNWOUND" in a for a in acts_all), acts_all


def test_dd_killswitch_unwinds():
    v = PaperVenue(price=100.0, cash=2.0, taker_fee=0.0)
    bot = CarryBot(v, CarryBotConfig(notional=1.0, leverage=1.0, dd_kill=0.10))
    bot.open()
    # force a big negative funding streak (longs receive -> our short PAYS)
    for _ in range(50):
        v.apply_funding(-0.01)
        if bot.step() and bot.state == "FLAT":
            break
    assert bot.state == "FLAT"


def test_live_requires_keys(monkeypatch):
    # run_live must bail out (no network) when demo keys are absent
    from algo_engine.carry_bot.live import run_live
    from algo_engine.carry_bot.bybit_venue import DEMO_BASE
    monkeypatch.delenv("BYBIT_API_KEY", raising=False)
    monkeypatch.delenv("BYBIT_API_SECRET", raising=False)
    assert run_live("BTCUSDT", 20.0, 1.0, 30.0, DEMO_BASE) == 2
