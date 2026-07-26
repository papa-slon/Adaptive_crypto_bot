from algo_engine.broker.paper import PaperBroker


def test_long_profit_increases_equity():
    b = PaperBroker(initial_equity=10_000, fee=0.0)
    b.update_price("BTCUSDT", 100.0)
    b.open_market("BTCUSDT", "long", qty=10.0)
    b.update_price("BTCUSDT", 110.0)
    assert b.get_equity() > 10_000  # unrealized gain visible
    res = b.close_market("BTCUSDT")
    assert res["pnl"] == 100.0      # (110-100)*10
    assert abs(b.get_equity() - 10_100.0) < 1e-9


def test_short_profit_on_price_drop():
    b = PaperBroker(initial_equity=10_000, fee=0.0)
    b.update_price("ETHUSDT", 100.0)
    b.open_market("ETHUSDT", "short", qty=5.0)
    b.update_price("ETHUSDT", 90.0)
    res = b.close_market("ETHUSDT")
    assert res["pnl"] == 50.0       # (100-90)*5


def test_fee_is_charged():
    b = PaperBroker(initial_equity=10_000, fee=0.001)
    b.update_price("BTCUSDT", 100.0)
    b.open_market("BTCUSDT", "long", qty=10.0)  # notional 1000 -> fee 1.0
    b.close_market("BTCUSDT")                    # notional 1000 -> fee 1.0
    assert abs(b.get_equity() - (10_000 - 2.0)) < 1e-9
