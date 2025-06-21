"""Пакет стратегий + фабрика по Settings.STRATEGY."""
from importlib import import_module
from adaptive_crypto_bot.config import get_settings

def factory():
    S = get_settings()
    name = getattr(S, "STRATEGY", "DCA")
    mod  = import_module(f"adaptive_crypto_bot.strategy.{name.lower()}_logic")
    # класс должен оканчиваться на 'Strategy'
    cls  = next(
        getattr(mod, attr) for attr in dir(mod)
        if attr.lower().startswith(name.lower()) and attr.endswith("Strategy")
    )
    return cls()
