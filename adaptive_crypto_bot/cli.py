"""CLI для запуска бота, тестов, отладки (python -m adaptive_crypto_bot.cli)."""
from __future__ import annotations
import asyncio, sys, importlib
import click
from adaptive_crypto_bot.utils.logger import setup as log_setup
from adaptive_crypto_bot.core         import main as core_main
from adaptive_crypto_bot.config       import get_settings

@click.group()
def cli() -> None:
    """Adapt Crypto Bot – Swiss-knife."""
    log_setup(get_settings().LOG_LEVEL)

@cli.command()
def run() -> None:
    """Запуск боевого event-loop."""
    asyncio.run(core_main.main())

@cli.command()
@click.option("--symbol", default="BTCUSDT", help="Любой тикер Binance.")
def tail(symbol: str) -> None:
    """Быстрый просмотр стрима в терминале (dev-tool)."""
    from adaptive_crypto_bot.exchanges.binance import BinanceClient
    cfg = get_settings()
    client = BinanceClient(cfg.BINANCE_API_KEY, cfg.BINANCE_SECRET, symbol)
    async def _tail():
        async for t in client.ticker_stream():
            click.echo(f"{t.ts}  {t.price:,.2f}  {t.qty:.4f}  {t.side}")
    asyncio.run(_tail())

@cli.command()
def test() -> None:
    """Запуск pytest внутри контейнера."""
    import pytest, pathlib
    code = pytest.main([str(pathlib.Path(__file__).parent.parent/"tests")])
    sys.exit(code)

if __name__ == "__main__":
    cli()
