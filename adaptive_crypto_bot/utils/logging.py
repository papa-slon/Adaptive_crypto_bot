"""Единый формат логов."""
import logging, os, sys
from adaptive_crypto_bot.config import get_settings

_FMT = "%(asctime)s %(levelname)s %(name)s | %(message)s"

def setup(name: str | None = None) -> logging.Logger:
    lvl = getattr(logging, get_settings().LOG_LEVEL.upper(), logging.INFO)
    logging.basicConfig(level=lvl, format=_FMT, stream=sys.stdout, force=True)
    return logging.getLogger(name or "bot")
