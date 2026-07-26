from __future__ import annotations

from dataclasses import dataclass


@dataclass
class BrokerPosition:
    symbol: str
    side: str        # "long" or "short"
    qty: float
    entry: float
    stop: float | None = None


class Broker:
    """Minimal broker interface used by the live loop.

    Implementations: PaperBroker (simulated) and BybitBroker (real demo/live).
    The live loop only ever calls these methods, so swapping paper <-> real is
    a one-line change.
    """

    def get_equity(self) -> float:
        raise NotImplementedError

    def get_last_price(self, symbol: str) -> float:
        raise NotImplementedError

    def get_position(self, symbol: str) -> BrokerPosition | None:
        raise NotImplementedError

    def open_market(self, symbol: str, side: str, qty: float, stop: float | None = None) -> dict:
        """Open a position at market. `stop` is an absolute protective price."""
        raise NotImplementedError

    def close_market(self, symbol: str) -> dict:
        """Flatten the current position at market (reduce-only)."""
        raise NotImplementedError

    def name(self) -> str:
        return type(self).__name__
