"""Реестр стратегий + базовый абстрактный класс."""
from __future__ import annotations
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Dict, Type

_STRATS: Dict[str, "BaseStrategy"] = {}

def register(cls):
    _STRATS[cls.__name__.lower()] = cls
    return cls

def get(name: str):
    return _STRATS[name.lower()]

class BaseStrategy(ABC):
    """Базовый интерфейс стратегии."""

    def __init__(self, executor) -> None:
        self.ex = executor

    # события рынка / системы
    @abstractmethod
    async def on_tick(self, tick: dict): ...
    async def on_start(self): ...
    async def on_stop(self): ...
