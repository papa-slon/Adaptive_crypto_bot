"""Live / demo trading loop — auto mode with a hard kill-switch.

What it does each cycle:
  1. Pull recent klines, keep only CLOSED bars.
  2. If a new bar closed, compute the strategy signal using the REAL broker
     position (so exits are correct).
  3. Mark equity -> RiskManager updates the daily-loss and max-drawdown gates.
  4. If the kill-switch tripped: flatten and STOP opening new trades.
  5. Otherwise act: size via RiskManager, open/close at market via the broker.

Stopping is easy and always available:
  * create an empty file named `STOP` in the working dir -> graceful halt,
  * or press Ctrl+C -> graceful halt (optionally flatten).

It defaults to Bybit DEMO and the PaperBroker if no keys are present. Going
live requires demo=False in config AND env AE_ALLOW_LIVE=1 — two locks, on
purpose. Decrypted secrets are never logged.
"""
from __future__ import annotations

import logging
import os
import time
from pathlib import Path

from . import data
from .broker.base import Broker, BrokerPosition
from .broker.paper import PaperBroker
from .config import EngineConfig
from .risk import RiskManager
from .strategies import build as build_strategy
from .strategies.base import PositionView

log = logging.getLogger("algo_engine.live")
_STOP_FILE = "STOP"


def make_broker(cfg: EngineConfig) -> Broker:
    """Build the broker. Bybit if keys are in env, else PaperBroker (dry run)."""
    key = os.getenv("BYBIT_API_KEY", "")
    secret = os.getenv("BYBIT_API_SECRET", "")
    if not key or not secret:
        log.warning("No BYBIT_API_KEY/SECRET in env -> PAPER mode (no real orders).")
        return PaperBroker(initial_equity=cfg.initial_equity, fee=cfg.fee)

    if not cfg.demo:
        if os.getenv("AE_ALLOW_LIVE") != "1":
            raise RuntimeError(
                "Refusing LIVE trading: set AE_ALLOW_LIVE=1 to confirm real-money orders."
            )
        log.warning("LIVE trading enabled (real money).")
    from .broker.bybit import BybitBroker

    return BybitBroker(api_key=key, api_secret=secret, demo=cfg.demo)


def _fetch_days_for(cfg: EngineConfig, warmup: int) -> float:
    bars_needed = warmup + 80
    return max(1.0, bars_needed * cfg.interval_min / 1440.0)


def run(cfg: EngineConfig, broker: Broker | None = None, max_cycles: int | None = None) -> None:
    strategy = build_strategy(cfg.strategy, **cfg.strategy_params)
    broker = broker or make_broker(cfg)
    rm = RiskManager(cfg.risk, broker.get_equity() or cfg.initial_equity)
    fetch_days = _fetch_days_for(cfg, strategy.warmup)

    log.info(
        "live start | %s %s %dm | broker=%s | risk=%.2f%%/trade dayLimit=%.0f%% maxDD=%.0f%%",
        cfg.strategy, cfg.symbol, cfg.interval_min, broker.name(),
        cfg.risk.risk_pct * 100, cfg.risk.daily_loss_limit * 100, cfg.risk.max_drawdown * 100,
    )

    last_bar_ts = None
    cycles = 0
    try:
        while True:
            if Path(_STOP_FILE).exists():
                log.warning("STOP file detected -> graceful halt (position left as-is).")
                break
            if max_cycles is not None and cycles >= max_cycles:
                break
            cycles += 1

            try:
                df = data.fetch_bybit_klines(cfg.symbol, cfg.interval_min, days=fetch_days)
            except Exception as exc:  # network hiccup -> wait and retry, never crash
                log.error("data fetch failed: %s", exc)
                time.sleep(cfg.poll_seconds)
                continue

            closed = df.iloc[:-1]  # drop the still-forming bar
            if len(closed) < strategy.warmup + 1:
                time.sleep(cfg.poll_seconds)
                continue

            bar_ts = closed.index[-1]
            if bar_ts == last_bar_ts:
                time.sleep(cfg.poll_seconds)
                continue
            last_bar_ts = bar_ts

            _on_new_bar(cfg, strategy, broker, rm, closed)
            time.sleep(cfg.poll_seconds)
    except KeyboardInterrupt:
        log.warning("Ctrl+C -> graceful halt.")


def _on_new_bar(cfg, strategy, broker: Broker, rm: RiskManager, closed) -> None:
    prepared = strategy.prepare(closed)
    i = len(prepared) - 1
    bar = prepared.iloc[i]

    broker_pos = broker.get_position(cfg.symbol)
    if isinstance(broker, PaperBroker):
        broker.update_price(cfg.symbol, float(bar["close"]))

    # --- risk anchors + kill-switch ---
    equity = broker.get_equity()
    rm.mark_equity(equity, day_key=str(bar.name.date()))
    if rm.killed:
        if broker_pos is not None:
            log.error("KILL-SWITCH (%s) -> flattening.", rm.kill_reason)
            broker.close_market(cfg.symbol)
        return

    posview = None
    bars_held = 0
    if broker_pos is not None:
        # bars_held is best-effort in live (broker doesn't track it); 0 is safe
        posview = PositionView(
            side=broker_pos.side,
            entry=broker_pos.entry,
            stop=broker_pos.stop or 0.0,
            bars_held=bars_held,
        )

    sig = strategy.signal(prepared, i, posview)
    log.info(
        "bar %s close=%.4f eq=%.2f pos=%s sig=%s (%s)",
        bar.name, float(bar["close"]), equity,
        broker_pos.side if broker_pos else "flat", sig.action, sig.reason,
    )

    # --- act ---
    if broker_pos is not None and sig.action == "flat":
        res = broker.close_market(cfg.symbol)
        log.info("CLOSE %s -> %s", cfg.symbol, res)
    elif broker_pos is None and sig.action in ("long", "short") and sig.stop is not None:
        entry_ref = float(bar["close"])
        sz = rm.size(equity, entry_ref, sig.stop)
        if not sz.allowed:
            log.info("entry blocked by risk: %s", sz.reason)
            return
        res = broker.open_market(cfg.symbol, sig.action, sz.qty, stop=sig.stop)
        log.info("OPEN %s %s qty=%.6f stop=%.4f -> %s", sig.action, cfg.symbol, sz.qty, sig.stop, res)
