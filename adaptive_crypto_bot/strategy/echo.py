"""Базовая стратегия-заглушка: вывод тиков в лог."""
from __future__ import annotations
import logging

log = logging.getLogger(__name__)

class EchoStrategy:
    def __init__(self, sink): self.sink = sink

    async def on_tick(self, tick: dict):
        log.info("ECHO %s", tick)
        # пример работы с ордер-синком
        # await self.sink.send({"action": "noop"})
