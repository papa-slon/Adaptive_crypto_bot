"""Упрощённый клиент BingX (Perp/Spot – public + private)."""
from __future__ import annotations
import hmac, hashlib, time, aiohttp, json, logging, urllib.parse, asyncio
from adaptive_crypto_bot.config import get_settings
from adaptive_crypto_bot.utils.logging import setup

log = setup()
S   = get_settings()

_BASE_URL = "https://open-api.bingx.com"
_WS_URL   = "wss://open-api.bingx.com/market"          # public quote-stream


# ───────────────────────── REST ──────────────────────────
class BingXREST:
    def __init__(self) -> None:
        self._s = aiohttp.ClientSession()

    async def _req(self, method: str, path: str, auth: bool = False, **params) -> dict:
        ts = int(time.time() * 1000)
        params["timestamp"] = ts
        params = {k: v for k, v in params.items() if v is not None}
        q = urllib.parse.urlencode(params, True)
        headers: dict[str, str] = {"Content-Type": "application/x-www-form-urlencoded"}
        if auth:
            sig = hmac.new(S.BINGX_SECRET.encode(), q.encode(), hashlib.sha256).hexdigest()
            headers["X-BX-APIKEY"] = S.BINGX_API_KEY
            headers["X-BX-SIGNATURE"] = sig
        url = f"{_BASE_URL}{path}"
        async with self._s.request(method, url, headers=headers, data=q) as r:
            data = await r.json()
            if r.status != 200 or data.get("code") not in (0, "0"):
                raise RuntimeError(f"BingX error {data}")
            return data.get("data", data)

    # health-ping
    async def ping(self) -> dict:
        return await self._req("GET", "/openApi/spot/v1/common/time")

    async def new_order(self, side: str, qty: float, price: float | None = None):
        typ = "LIMIT" if price else "MARKET"
        return await self._req(
            "POST", "/openApi/spot/v1/trade/order", True,
            symbol=S.SYMBOL, side=side.upper(), type=typ,
            quantity=qty, price=price, timeInForce="GTC" if price else None
        )

    async def close(self): await self._s.close()


# ──────────────────────── WEBSOCKET ───────────────────────
async def trade_socket():
    """
    BingX public trade-stream (конвертация к унифицированному тик-формату).
    NB: schema упрощена до `{"data":[{...}]}`.
    """
    async with aiohttp.ClientSession() as s, s.ws_connect(_WS_URL) as ws:
        # подписка на торговый поток символа
        sub = {"id": 1, "type": "SUBSCRIBE", "topic": f"trade:{S.SYMBOL}"}
        await ws.send_str(json.dumps(sub))

        async for msg in ws:
            if msg.type is aiohttp.WSMsgType.TEXT:
                d = json.loads(msg.data)
                if "data" not in d:      # ping/ack etc.
                    continue
                for t in d["data"]:
                    yield {
                        "ts": int(t["ts"]),
                        "price": float(t["p"]),
                        "qty": float(t["v"]),
                        "side": t["s"],
                        "src": "BGX"
                    }
            elif msg.type is aiohttp.WSMsgType.ERROR:
                log.error("BingX WS error: %s", msg)
                break


# быстрый самотест
if __name__ == "__main__":                            # pragma: no cover
    async def _test():
        async for t in trade_socket():
            print(t)
    asyncio.run(_test())
