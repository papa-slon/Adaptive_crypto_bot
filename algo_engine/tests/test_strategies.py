from algo_engine.data import synthetic_ohlcv
from algo_engine.strategies import build
from algo_engine.strategies.base import PositionView, Signal


def test_prepare_adds_columns_and_signal_is_valid():
    df = synthetic_ohlcv(n=2000, seed=21, trend_strength=0.15)
    for name in ("trend_breakout", "mean_reversion"):
        strat = build(name)
        prepared = strat.prepare(df)
        assert len(prepared) == len(df)
        sig = strat.signal(prepared, len(prepared) - 1, None)
        assert isinstance(sig, Signal)
        assert sig.action in ("long", "short", "flat", "none")
        if sig.action in ("long", "short"):
            assert sig.stop is not None


def test_entries_only_when_flat():
    df = synthetic_ohlcv(n=2000, seed=22, trend_strength=0.2)
    strat = build("trend_breakout")
    prepared = strat.prepare(df)
    held = PositionView(side="long", entry=100.0, stop=99.0, bars_held=3)
    # while holding, the strategy must never emit a fresh entry (only none/flat)
    for i in range(strat.warmup, len(prepared)):
        sig = strat.signal(prepared, i, held)
        assert sig.action in ("none", "flat")


def test_stop_is_on_correct_side():
    df = synthetic_ohlcv(n=3000, seed=23, trend_strength=0.25)
    strat = build("trend_breakout")
    prepared = strat.prepare(df)
    for i in range(strat.warmup, len(prepared)):
        sig = strat.signal(prepared, i, None)
        close = float(prepared.iloc[i]["close"])
        if sig.action == "long":
            assert sig.stop < close      # long stop below price
        elif sig.action == "short":
            assert sig.stop > close      # short stop above price
