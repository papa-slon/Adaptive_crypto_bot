from __future__ import annotations

from .base import Broker, BrokerPosition


class PaperBroker(Broker):
    """Simulated broker: fills at the last price you feed it, tracks one
    position and a cash equity. Used for dry runs and tests — no network, no
    keys, no risk. Behaves like a single-position perpetual-futures account.
    """

    def __init__(self, initial_equity: float = 10_000.0, fee: float = 0.00055) -> None:
        self.equity = initial_equity
        self.fee = fee
        self._last: dict[str, float] = {}
        self._pos: dict[str, BrokerPosition] = {}

    # the live loop feeds the latest close before acting
    def update_price(self, symbol: str, price: float) -> None:
        self._last[symbol] = price

    def get_equity(self) -> float:
        # realized cash + unrealized on the open position
        unreal = 0.0
        for sym, p in self._pos.items():
            last = self._last.get(sym, p.entry)
            unreal += (last - p.entry) * p.qty if p.side == "long" else (p.entry - last) * p.qty
        return self.equity + unreal

    def get_last_price(self, symbol: str) -> float:
        return self._last.get(symbol, 0.0)

    def get_position(self, symbol: str) -> BrokerPosition | None:
        return self._pos.get(symbol)

    def open_market(self, symbol: str, side: str, qty: float, stop: float | None = None) -> dict:
        price = self._last[symbol]
        self.equity -= self.fee * price * qty
        self._pos[symbol] = BrokerPosition(symbol, side, qty, price, stop)
        return {"ok": True, "filled": qty, "price": price, "side": side}

    def close_market(self, symbol: str) -> dict:
        p = self._pos.pop(symbol, None)
        if p is None:
            return {"ok": True, "filled": 0.0}
        price = self._last[symbol]
        pnl = (price - p.entry) * p.qty if p.side == "long" else (p.entry - price) * p.qty
        self.equity += pnl - self.fee * price * p.qty
        return {"ok": True, "filled": p.qty, "price": price, "pnl": pnl}
