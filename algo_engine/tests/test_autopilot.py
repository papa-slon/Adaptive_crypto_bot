"""Tests for the autopilot's coin-rotation policy.

The rotation rules are the difference between a carry portfolio that earns and
one that bleeds fees: an earlier experiment showed that toggling positions on
every funding wobble turns a positive edge into a -25%..-38% loss. These tests
pin the anti-churn behaviour. Offline (fake venues, no network).
"""
from __future__ import annotations

import logging
import time

import pytest

from algo_engine.carry_bot import autopilot as ap
from algo_engine.carry_bot.scanner import Candidate

LOG = logging.getLogger("test-autopilot")


class FakeBot:
    def __init__(self):
        self.state = "HOLD"
        self.unwound_reason = None

    def step(self):
        return []

    def unwind(self, reason):
        self.state = "FLAT"
        self.unwound_reason = reason
        return [f"UNWOUND ({reason})"]


class FakeVenue:
    def __init__(self, symbol):
        self.symbol = symbol
        self.funding_collected = 0.0

    def equity(self): return 100.0
    def mark_price(self): return 50.0
    def spot_base_qty(self): return 1.0
    def perp_short_qty(self): return 1.0
    def perp_margin_ratio(self): return 0.5
    def refresh_funding(self): return 0.0


def make_pilot(**kw):
    pilot = ap.Autopilot("bybit-demo", ("k", "s"), capital=300.0, slots=2,
                         leverage=1.0, log=LOG, **kw)
    # opening a slot is faked: no network, no orders
    def fake_open(cand):
        pilot.slots[cand.symbol] = ap.Slot(cand.symbol, FakeVenue(cand.symbol), FakeBot(), cand)
        return True
    pilot.open_slot = fake_open
    return pilot


def cand(symbol, mean, score=None):
    return Candidate(symbol=symbol, mean_funding=mean, std_funding=0.0, n_obs=50,
                     score=score if score is not None else mean, ann_pct=mean * 3 * 365 * 100)


def test_slot_notional_reserves_perp_margin():
    """Capital per slot must cover the spot leg AND the perp margin."""
    p1 = ap.Autopilot("bybit-demo", ("k", "s"), 300.0, 3, 1.0, LOG)
    assert p1.slot_notional() == pytest.approx(50.0)     # 100/slot over (1 + 1/1)
    p3 = ap.Autopilot("bybit-demo", ("k", "s"), 300.0, 3, 3.0, LOG)
    assert p3.slot_notional() == pytest.approx(75.0)     # 100/slot over (1 + 1/3)


def test_rotate_fills_empty_slots_with_best_candidates():
    pilot = make_pilot()
    pilot.rotate([cand("AUSDT", 0.0004), cand("BUSDT", 0.0003), cand("CUSDT", 0.0002)])
    assert set(pilot.slots) == {"AUSDT", "BUSDT"}        # 2 slots, best two


def test_does_not_churn_for_a_marginal_improvement():
    """A slightly better payer must NOT trigger a paid round trip."""
    pilot = make_pilot()
    pilot.rotate([cand("AUSDT", 0.0004), cand("BUSDT", 0.0003)])
    for s in pilot.slots.values():
        s.opened_at = time.time() - 6 * 86400            # long past the 3-day min hold
    before = set(pilot.slots)
    # CUSDT is only ~13% better than the worst held — below the switch_edge
    pilot.rotate([cand("AUSDT", 0.0004), cand("CUSDT", 0.00034), cand("BUSDT", 0.0003)])
    assert set(pilot.slots) == before, "rotated for a marginal edge (fee trap)"


def test_rotates_when_the_edge_is_large():
    pilot = make_pilot()
    pilot.rotate([cand("AUSDT", 0.0004), cand("BUSDT", 0.0001)])
    for s in pilot.slots.values():
        s.opened_at = time.time() - 6 * 86400
    pilot.rotate([cand("AUSDT", 0.0004), cand("BIGUSDT", 0.0009), cand("BUSDT", 0.0001)])
    assert "BIGUSDT" in pilot.slots and "BUSDT" not in pilot.slots


def test_min_hold_blocks_immediate_rotation():
    """Even a big edge must not flip a position opened seconds ago."""
    pilot = make_pilot()
    pilot.rotate([cand("AUSDT", 0.0004), cand("BUSDT", 0.0001)])
    held_before = set(pilot.slots)
    pilot.rotate([cand("AUSDT", 0.0004), cand("BIGUSDT", 0.0009), cand("BUSDT", 0.0001)])
    assert set(pilot.slots) == held_before, "rotated before the minimum hold elapsed"


def test_drops_a_slot_whose_funding_went_negative():
    pilot = make_pilot()
    pilot.rotate([cand("AUSDT", 0.0004), cand("BUSDT", 0.0003)])
    assert "BUSDT" in pilot.slots
    pilot.rotate([cand("AUSDT", 0.0004), cand("BUSDT", -0.0002)])
    assert "BUSDT" not in pilot.slots, "kept a slot that is now PAYING funding"


def test_a_dead_slot_is_reaped_on_step():
    """If a bot unwinds itself (kill-switch), the slot frees up."""
    pilot = make_pilot()
    pilot.rotate([cand("AUSDT", 0.0004)])
    pilot.slots["AUSDT"].bot.state = "FLAT"
    pilot.step_all()
    assert "AUSDT" not in pilot.slots


def test_empty_scan_holds_position_instead_of_closing():
    pilot = make_pilot()
    pilot.rotate([cand("AUSDT", 0.0004)])
    pilot.rotate([])                                     # scanner returned nothing
    assert "AUSDT" in pilot.slots, "a failed scan must not liquidate the book"
