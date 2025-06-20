
import redis, os, asyncio, json, websockets, time, math
r = redis.Redis(host=os.getenv("REDIS_HOST","127.0.0.1"),decode_responses=True)
WS = "wss://open-api.bingx.com/market"
class MMLite:
    def __init__(self, symbol, lot=0.002, inv_max=0.005):
        self.sym=symbol; self.lot=lot; self.inv=0; self.inv_max=inv_max
    async def run(self):
        async with websockets.connect(WS,ping_interval=None) as ws:
            await ws.send(json.dumps({"id":"d1","reqType":"sub","dataType":"depth200","dataSymbol":self.sym}))
            while True:
                msg=json.loads(await ws.recv())
                if 'data' not in msg: continue
                depth=msg['data']
                bid=float(depth['bids'][0][0]); ask=float(depth['asks'][0][0])
                mid=(bid+ask)/2; spread=max((ask-bid), 0.0002*mid)
                my_bid=round(mid-0.5*spread,2); my_ask=round(mid+0.5*spread,2)
                # pseudo order place
                r.xadd("orders:new",{"sym":self.sym,"side":"both","bid":my_bid,"ask":my_ask,"qty":self.lot})
