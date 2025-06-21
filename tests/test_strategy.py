import asyncio
from adaptive_crypto_bot.core.strategy import DcaStrategy
from adaptive_crypto_bot.core.models   import Tick, Side
class DummyExec:
    async def place_order(self, side, qty, price):
        from adaptive_crypto_bot.core.models import Order
        return Order(order_id="1", symbol="BTCUSDT", side=side, qty=qty,
                     price=price, status="NEW", exchange="bin", created_at=0)
async def test_slot_opens():
    s = DcaStrategy()
    t = Tick(ts=0, price=60_000, qty=0.01, side=Side.BUY, src="BIN")
    await s.on_tick(t, DummyExec())
    assert len(s.slots)==1
pytest_plugins = ("pytest_asyncio",)
