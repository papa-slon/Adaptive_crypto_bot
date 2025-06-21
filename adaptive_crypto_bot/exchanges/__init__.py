"""Мэппинг названия биржи → клиентского класса."""
from __future__ import annotations
from importlib import import_module
from functools  import lru_cache

_MAPPING = {
    "BINANCE": ("adaptive_crypto_bot.exchanges.binance", "BinanceREST"),
    "BINGX"  : ("adaptive_crypto_bot.exchanges.bingx"  , "BingxREST"),
}

@lru_cache
def get_client(name: str):
    mod_path, cls_name = _MAPPING[name.upper()]
    mod = import_module(mod_path)
    return getattr(mod, cls_name)()        # type: ignore[return-value]
