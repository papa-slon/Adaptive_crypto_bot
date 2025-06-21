"""Единое подключение логов.

Оставляем utils.logging.setup, но даём более короткий импорт:
    from adaptive_crypto_bot.logging_setup import setup
"""
from adaptive_crypto_bot.utils.logging import setup  # re-export
__all__ = ["setup"]
