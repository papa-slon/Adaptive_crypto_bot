"""Venue registry: one place that maps a venue name to a configured adapter.

Demo endpoints are the only defaults. Real-money endpoints exist but the CLI
refuses them without an explicit confirmation flag, so a typo can never point
the bot at live funds.
"""
from __future__ import annotations

from .bybit_venue import (  # re-exported so callers need one import
    DEMO_BASE as BYBIT_DEMO,
    MAINNET_BASE as BYBIT_MAINNET,
    TESTNET_BASE as BYBIT_TESTNET,
    BybitVenue,
    PreflightError,
)

# name -> (adapter class, base_url, is_demo)
_REGISTRY: dict[str, tuple[type, str, bool]] = {
    "bybit-demo": (BybitVenue, BYBIT_DEMO, True),
    "bybit-testnet": (BybitVenue, BYBIT_TESTNET, True),
    "bybit-mainnet": (BybitVenue, BYBIT_MAINNET, False),
}

try:  # BingX is optional so a broken/missing adapter cannot stop Bybit from running
    from .bingx_venue import MAINNET_BASE as BINGX_MAINNET, VST_BASE as BINGX_VST, BingXVenue

    _REGISTRY["bingx-demo"] = (BingXVenue, BINGX_VST, True)
    _REGISTRY["bingx-mainnet"] = (BingXVenue, BINGX_MAINNET, False)
except ImportError:  # pragma: no cover - only when the adapter is absent
    pass


def venue_choices() -> list[str]:
    return sorted(_REGISTRY)


def is_demo(name: str) -> bool:
    return _REGISTRY[name][2] if name in _REGISTRY else False


def build_venue(name: str, api_key: str, api_secret: str, *, symbol: str,
                enable_trading: bool = False, leverage: float = 1.0):
    if name not in _REGISTRY:
        raise ValueError(f"unknown venue '{name}'; choose one of {venue_choices()}")
    cls, base_url, _demo = _REGISTRY[name]
    return cls(api_key, api_secret, symbol=symbol, base_url=base_url,
               enable_trading=enable_trading, leverage=leverage)


__all__ = ["PreflightError", "build_venue", "venue_choices", "is_demo"]
