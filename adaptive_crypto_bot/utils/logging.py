"""Единая точка конфигурации логирования для всех модулей пакета."""
from __future__ import annotations
import logging, os, sys
from functools import lru_cache

_FMT = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
_DATEFMT = "%H:%M:%S"

@lru_cache
def setup(name: str | None = None) -> logging.Logger:
    level = os.getenv("LOG_LEVEL", "INFO").upper()
    logging.basicConfig(
        level   = level,
        format  = _FMT,
        datefmt = _DATEFMT,
        handlers=[logging.StreamHandler(sys.stdout)],
    )
    return logging.getLogger(name or __name__)
