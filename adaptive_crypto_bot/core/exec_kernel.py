"""Exec-kernel: единая точка старта внутренних задач бота.

Запускает:
  • data_bus (нормализация тиков ➜ Redis-стрим)
  • стратегию (DCAStrategy или иную, указанную в Settings.STRATEGY)
  • сервисы: OrderManager, RiskManager
"""

from __future__ import annotations
import asyncio, logging, signal
from contextlib import suppress
from adaptive_crypto_bot.logging_setup import setup
from adaptive_crypto_bot.core import data_bus
from adaptive_crypto_bot.config import get_settings
from adaptive_crypto_bot.strategy import factory as strategy_factory
from adaptive_crypto_bot.services.order_manager import OrderManager
from adaptive_crypto_bot.services.risk_manager  import RiskManager

log = setup()
S   = get_settings()


async def _run_with_restart(coro_factory, name: str, delay: float = 3.0):
    """Запуск корутины с автоперезапуском при исключениях."""
    while True:
        try:
            log.info("▶ старт %s", name)
            await coro_factory()
        except asyncio.CancelledError:
            raise
        except Exception as e:                         # pylint: disable=broad-except
            log.exception("❌ %s упал: %s – рестарт через %.1fs", name, e, delay)
            await asyncio.sleep(delay)


async def _task_data_bus():
    await data_bus.main()


async def _task_strategy():
    strat = strategy_factory()
    await strat.run()


async def _task_order_manager():
    om = OrderManager()
    await om.run()


async def _task_risk_manager():
    rm = RiskManager()
    await rm.run()


async def main() -> None:                              # noqa: D401
    """Главная корутина – собирает и запускает все задачи."""
    tasks = [
        asyncio.create_task(_run_with_restart(_task_data_bus,       "data_bus")),
        asyncio.create_task(_run_with_restart(_task_strategy,       "strategy")),
        asyncio.create_task(_run_with_restart(_task_order_manager,  "order_manager")),
        asyncio.create_task(_run_with_restart(_task_risk_manager,   "risk_manager")),
    ]

    # graceful-shutdown по SIGINT / SIGTERM
    stop_event = asyncio.Event()

    def _graceful_shutdown(*_sig):
        log.warning("↩ получен сигнал завершения – останавливаем задачи…")
        stop_event.set()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        with suppress(ValueError):
            loop.add_signal_handler(sig, _graceful_shutdown, sig)

    await stop_event.wait()
    for t in tasks:
        t.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)
    log.info("✅ exec_kernel завершён")


if __name__ == "__main__":
    asyncio.run(main())
