"""Абстрактный интерфейс любой торговой стратегии."""
from __future__ import annotations
from abc import ABC, abstractmethod
from typing import Protocol, Iterable, Mapping, Any

class Exchange(Protocol):
    async def new_order(self, side: str, qty: float, price: float | None = None) -> Mapping[str, Any]: ...
    async def ping(self) -> Mapping[str, Any]: ...

class BaseStrategy(ABC):
    """Общий каркас: принимает тики → генерирует ордер-команды."""
    def __init__(self, exch: Exchange): self.exch = exch

    # тик — dict(ts, price, qty, side, src)
    @abstractmethod
    async def on_tick(self, tick: dict[str, Any]) -> None: ...

    async def on_ticks(self, ticks: Iterable[dict[str, Any]]) -> None:
        for t in ticks:
            await self.on_tick(t)
