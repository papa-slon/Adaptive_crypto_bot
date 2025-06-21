"""Простейший risk-менеджер: следит, что биржа доступна и нет «зависших» ордеров."""
from __future__ import annotations
import asyncio, logging, datetime as dt
from adaptive_crypto_bot.services.executor import Executor
from adaptive_crypto_bot.utils.logging     import setup

log = setup()

HANGING_SEC = 60

async def monitor():
    ex = Executor("BINANCE")
    while True:
        try:
            await ex.rest.ping()
        except Exception as e:
            log.error("Ping failed: %s", e)
        await asyncio.sleep(10)

async def cancel_hanging():
    ex = Executor("BINANCE")
    while True:
        try:
            now = dt.datetime.utcnow().timestamp()*1000
            open_orders = await ex.rest.open_orders()
            for o in open_orders:
                if now - int(o["updateTime"]) > HANGING_SEC*1000:
                    await ex.rest.cancel_order(o["symbol"], o["orderId"])
                    log.warning("Cancelled hanging order %s", o["orderId"])
        except Exception as e:
            log.exception("cancel_hanging error: %s", e)
        await asyncio.sleep(15)

async def main():
    await asyncio.gather(monitor(), cancel_hanging())

if __name__ == "__main__":
    asyncio.run(main())
