from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from .risk import RiskConfig


@dataclass
class EngineConfig:
    symbol: str = "BTCUSDT"
    interval_min: int = 5
    strategy: str = "trend_breakout"
    strategy_params: dict = field(default_factory=dict)

    initial_equity: float = 10_000.0
    fee: float = 0.00055
    slippage: float = 0.0005

    risk: RiskConfig = field(default_factory=RiskConfig)

    # live-only
    demo: bool = True          # Bybit demo endpoint; live needs demo=False + env gate
    poll_seconds: int = 10     # how often the live loop wakes to check for a new bar
    history_days: float = 10.0 # how much history to seed indicators on live start

    @staticmethod
    def from_yaml(path: str | Path) -> "EngineConfig":
        import yaml  # PyYAML — optional dep; only needed for YAML config

        raw = yaml.safe_load(Path(path).read_text()) or {}
        risk_raw = raw.pop("risk", {}) or {}
        cfg = EngineConfig(**{k: v for k, v in raw.items() if k != "risk"})
        cfg.risk = RiskConfig(**risk_raw)
        return cfg
