"""
algo_engine — a clean, self-contained crypto trading engine.

Built ALONGSIDE the existing scaffold (src/, adaptive_crypto_bot/) without
touching it. Nothing here runs automatically: backtests are offline, and
live/demo trading only happens when you explicitly start algo_engine.live
with your own Bybit credentials.

Honest contract: this gives you a *tested, risk-managed framework* — not a
guaranteed-profit machine. The edge (if any) is something YOU verify on the
backtest and on demo before risking real money.
"""

__version__ = "0.1.0"
