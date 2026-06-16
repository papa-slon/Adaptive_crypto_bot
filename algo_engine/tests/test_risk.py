from algo_engine.risk import RiskConfig, RiskManager


def test_fixed_fractional_sizing_risks_exactly_pct():
    rm = RiskManager(RiskConfig(risk_pct=0.005, max_leverage=100), initial_equity=10_000)
    res = rm.size(equity=10_000, entry=100.0, stop=99.0)  # stop distance = 1.0
    assert res.allowed
    # loss if stopped = qty * stop_distance == 0.5% of equity
    loss_at_stop = res.qty * 1.0
    assert abs(loss_at_stop - 50.0) < 1e-6


def test_leverage_cap_limits_notional():
    rm = RiskManager(RiskConfig(risk_pct=0.05, max_leverage=5), initial_equity=10_000)
    # tiny stop distance would imply a huge qty; leverage cap must clamp it
    res = rm.size(equity=10_000, entry=100.0, stop=99.99)
    assert res.allowed
    assert res.notional <= 10_000 * 5 + 1e-6


def test_daily_loss_limit_blocks_entry():
    rm = RiskManager(RiskConfig(daily_loss_limit=-0.06), initial_equity=10_000)
    rm.mark_equity(10_000, day_key="2026-01-01")
    rm.mark_equity(9_300, day_key="2026-01-01")  # -7% on the day
    ok, reason = rm.can_enter(9_300)
    assert not ok and "daily" in reason


def test_kill_switch_on_max_drawdown():
    rm = RiskManager(RiskConfig(max_drawdown=-0.25), initial_equity=10_000)
    rm.mark_equity(12_000, day_key="2026-01-01")  # new peak
    rm.mark_equity(8_900, day_key="2026-01-02")   # -25.8% from peak
    assert rm.killed
    ok, reason = rm.can_enter(8_900)
    assert not ok and "KILL" in reason


def test_below_min_notional_rejected():
    rm = RiskManager(RiskConfig(risk_pct=0.005, min_notional=50), initial_equity=100)
    res = rm.size(equity=100, entry=100.0, stop=50.0)  # qty tiny -> notional small
    assert not res.allowed
