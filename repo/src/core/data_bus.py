
"""Real‑time market feed normaliser and Redis publisher."""
import asyncio, json, time, websockets, redis, os

BIN_WS = "wss://stream.binance.com:9443/ws/btcusdt@trade"
BGX_WS = "wss://open-api.bingx.com/market"

STREAM = "ticks:core"
r = redis.Redis(host=os.getenv("REDIS_HOST","127.0.0.1"), decode_responses=True)

async def producer(uri, src):
    async with websockets.connect(uri, ping_interval=None) as ws:
        while True:
            msg = await ws.recv()
            data = json.loads(msg)
            if src == "BIN":
                tick = {
                    "ts": int(data["T"]),
                    "price": float(data["p"]),
                    "qty": float(data["q"]),
                    "side": "buy" if data["m"] is False else "sell",
                    "src": src
                }
            else:
                # Simplified: assume bingx schema {"data":[{ ... }]}
                tick_raw = data["data"][0]
                tick = {
                    "ts": int(tick_raw["ts"]),
                    "price": float(tick_raw["p"]),
                    "qty": float(tick_raw["v"]),
                    "side": tick_raw["s"],
                    "src": src
                }
            if 0 < tick["qty"] < 1e4:
                r.xadd(STREAM, tick, maxlen=500000, approximate=True)

async def main():
    await asyncio.gather(
        producer(BIN_WS, "BIN"),
        producer(BGX_WS, "BGX")
    )

if __name__ == "__main__":
    asyncio.run(main())
