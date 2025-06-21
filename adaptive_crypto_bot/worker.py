"""Entry-point that wires everything together and runs the strategy loop."""
import asyncio, logging, signal, sys
from redis.asyncio import Redis

from adaptive_crypto_bot.config         import get_settings
from adaptive_crypto_bot.utils.logging_config import setup_logging
from adaptive_crypto_bot.core.strategy  import DcaStrategy
from adaptive_crypto_bot.core.executor  import OrderExecutor

settings = get_settings()
setup_logging(settings.LOG_LEVEL)
log = logging.getLogger(__name__)


async def main():
    async with OrderExecutor("binance") as ex:
        r  = Redis(host=settings.REDIS_HOST, port=settings.REDIS_PORT, decode_responses=True)
        strat = DcaStrategy(r, ex.market)

        # graceful shutdown
        stop = asyncio.Future()                        # type: ignore

        for sig in (signal.SIGINT, signal.SIGTERM):
            asyncio.get_running_loop().add_signal_handler(sig, stop.set_result, None)

        await asyncio.gather(strat.run(), stop)
        await r.close()


if __name__ == "__main__":
    asyncio.run(main())
