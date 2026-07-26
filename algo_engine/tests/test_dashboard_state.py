"""Offline tests for the dashboard state layer + page assembly. No network."""
from __future__ import annotations

from collections import deque

from algo_engine.carry_bot.bot import CarryBot, CarryBotConfig
from algo_engine.carry_bot.state import (
    StateWriter,
    build_snapshot,
    read_history,
    read_state,
)
from algo_engine.carry_bot.venue import PaperVenue


def test_snapshot_and_roundtrip(tmp_path):
    v = PaperVenue(price=100.0, cash=2.0, taker_fee=0.0)
    bot = CarryBot(v, CarryBotConfig(notional=1.0, leverage=1.0))
    bot.open()
    bot.start_equity_snapshot = v.equity()
    v.apply_funding(0.001)
    snap = build_snapshot(v, bot, {"mode": "paper", "symbol": "BTCUSDT",
                                   "notional": 1.0, "leverage": 1.0},
                          deque(["OPEN carry"], maxlen=40), errors=0, started_at=0.0)
    assert snap["state"] == "HOLD" and snap["symbol"] == "BTCUSDT"
    assert snap["equity"] is not None and snap["funding_collected"] > 0

    sp = tmp_path / "state.json"
    hp = tmp_path / "hist.jsonl"
    w = StateWriter(str(sp), str(hp))
    w.update(snap); w.update(snap)
    assert read_state(str(sp))["symbol"] == "BTCUSDT"
    hist = read_history(str(hp))
    assert len(hist) == 2 and "equity" in hist[0]


def test_snapshot_survives_failing_venue():
    class Broken:
        def equity(self): raise RuntimeError("net down")
        def mark_price(self): raise RuntimeError("net down")
        def perp_short_qty(self): raise RuntimeError("x")
        def spot_base_qty(self): raise RuntimeError("x")
        def perp_margin_ratio(self): raise RuntimeError("x")
    class FakeBot: state = "HOLD"; start_equity_snapshot = None
    snap = build_snapshot(Broken(), FakeBot(), {"mode": "bybit-demo"},
                          deque(maxlen=40), errors=3, started_at=0.0)
    assert snap["state"] == "HOLD" and snap["equity"] is None and snap["errors"] == 3


def test_dashboard_page_and_api_import():
    from algo_engine.carry_bot import dashboard
    assert "CARRY" in dashboard._PAGE and "/api/state" in dashboard._PAGE
    assert read_state("/nonexistent/x.json") is None
    assert read_history("/nonexistent/x.jsonl") == []
