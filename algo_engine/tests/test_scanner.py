"""Tests for the funding scanner's selection rules — the logic that decides,
unattended, which coins the bot carries. Offline (no network)."""
from __future__ import annotations

from algo_engine.carry_bot.scanner import (
    annualise,
    rank_candidates,
    stats_from_series,
)


def _stats(**series):
    return {sym: stats_from_series(vals) for sym, vals in series.items()}


def test_rejects_negative_and_zero_funding():
    """We are SHORT the perp, so only coins where longs pay us are candidates."""
    stats = _stats(
        GOODUSDT=[0.0002] * 40,
        NEGUSDT=[-0.0003] * 40,
        FLATUSDT=[0.0] * 40,
    )
    picked = [c.symbol for c in rank_candidates(stats, top_n=5)]
    assert picked == ["GOODUSDT"]


def test_rejects_thin_history():
    stats = _stats(THINUSDT=[0.0005] * 5, SOLIDUSDT=[0.0002] * 40)
    picked = [c.symbol for c in rank_candidates(stats, top_n=5, min_obs=20)]
    assert picked == ["SOLIDUSDT"]


def test_spiky_coin_is_rejected_not_merely_ranked_last():
    """A coin that averaged well because of ONE outlier must not take a slot,
    even when there are free slots to fill."""
    spiky = [0.0] * 38 + [0.004, 0.0]
    steady = [0.0001] * 40
    stats = _stats(SPIKYUSDT=spiky, STEADYUSDT=steady)
    # both average the same — only their stability differs
    assert abs(stats_from_series(spiky)["mean"] - stats_from_series(steady)["mean"]) < 1e-12
    picked = [c.symbol for c in rank_candidates(stats, top_n=5)]
    assert picked == ["STEADYUSDT"], picked


def test_steady_outranks_equal_mean_noisy():
    stats = _stats(
        STEADYUSDT=[0.0002] * 40,
        NOISYUSDT=[0.0002 + (0.0003 if i % 2 else -0.0003) for i in range(40)],
    )
    ranked = rank_candidates(stats, top_n=2)
    assert ranked[0].symbol == "STEADYUSDT"
    assert ranked[0].score > ranked[1].score


def test_top_n_is_respected_and_sorted():
    stats = _stats(**{f"C{i}USDT": [0.0001 * (i + 1)] * 40 for i in range(6)})
    ranked = rank_candidates(stats, top_n=3)
    assert len(ranked) == 3
    assert [c.symbol for c in ranked] == ["C5USDT", "C4USDT", "C3USDT"]
    assert ranked[0].score >= ranked[1].score >= ranked[2].score


def test_annualise_matches_three_settlements_a_day():
    # 0.01% per 8h = 0.03%/day ≈ 10.95%/yr, simple (non-compounded)
    assert abs(annualise(0.0001) - 10.95) < 1e-9


def test_empty_universe_is_safe():
    assert rank_candidates({}, top_n=3) == []
