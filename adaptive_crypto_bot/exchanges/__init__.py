"""Реестр REST-клиентов конкретных бирж."""
from __future__ import annotations
from typing import Dict, Type

from adaptive_crypto_bot.exchanges.binance_client import BinanceREST
# 👉 при появлении новых бирж просто импортируем здесь
# from adaptive_crypto_bot.exchanges.bingx   import BingXREST

REST_CLIENTS: Dict[str, Type[BinanceREST]] = {
    "BINANCE": BinanceREST,
    # "BINGX":  BingXREST,
}

def get_client(name: str):
    return REST_CLIENTS[name.upper()]
