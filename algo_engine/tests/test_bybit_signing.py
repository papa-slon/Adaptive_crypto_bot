"""Offline tests for the Bybit adapter: deterministic HMAC signing + the
read-only/trading-disabled safety gate. No network."""
from __future__ import annotations

import hashlib
import hmac

import pytest

from algo_engine.carry_bot.bybit_venue import (
    DEMO_BASE,
    BybitTradingDisabled,
    BybitVenue,
    _RECV_WINDOW,
    _sign,
)


def test_sign_matches_reference_hmac():
    secret, ts, key, body = "topsecret", "1700000000000", "mykey", '{"a":1}'
    expected = hmac.new(
        secret.encode(), f"{ts}{key}{_RECV_WINDOW}{body}".encode(), hashlib.sha256
    ).hexdigest()
    assert _sign(secret, ts, key, body) == expected
    assert len(_sign(secret, ts, key, body)) == 64  # sha256 hex


def test_defaults_to_demo_and_readonly():
    v = BybitVenue("k", "s", symbol="BTCUSDT")
    assert v.base_url == DEMO_BASE          # never mainnet by default
    assert v.enable_trading is False


def test_order_methods_blocked_until_enabled():
    v = BybitVenue("k", "s")                 # read-only
    for call in (
        lambda: v.buy_spot(10.0),
        lambda: v.sell_spot_qty(0.001),
        lambda: v.open_short_perp(10.0, 1.0),
        lambda: v.reduce_short_perp_qty(0.001),
        lambda: v.add_perp_margin(5.0),
    ):
        with pytest.raises(BybitTradingDisabled):
            call()
