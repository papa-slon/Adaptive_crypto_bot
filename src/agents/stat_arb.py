
import redis, os, typing, math, json, collections
from core.indicators import ATR
r = redis.Redis(host=os.getenv("REDIS_HOST","127.0.0.1"), decode_responses=True)
def publish_order(sym, side, qty):
    r.xadd("orders:new", {"sym":sym,"side":side,"qty":qty})

class Pair:
    def __init__(self, a:str, b:str, beta:float, z_open=2.0, z_close=0.5):
        self.a, self.b, self.beta = a, b, beta
        self.z_open, self.z_close = z_open, z_close
        self.spread=collections.deque(maxlen=400)
        self.position=None
    def on_bars(self, bar_a, bar_b):
        s = math.log(bar_a.close) - self.beta*math.log(bar_b.close)
        self.spread.append(s)
        if len(self.spread)<400: return
        mu=sum(self.spread)/len(self.spread)
        sigma=math.sqrt(sum((x-mu)**2 for x in self.spread)/len(self.spread))
        z=(s-mu)/sigma if sigma else 0
        if not self.position and abs(z)>self.z_open:
            side="short" if z>0 else "long"
            self.open(side, bar_a.close, bar_b.close)
        elif self.position and abs(z)<self.z_close:
            self.close()
    def open(self, side, pa,pb):
        qty=0.001
        if side=="long":
            publish_order(self.a,"buy",qty)
            publish_order(self.b,"sell",qty*self.beta)
        else:
            publish_order(self.a,"sell",qty)
            publish_order(self.b,"buy",qty*self.beta)
        self.position={"side":side,"qty":qty}
    def close(self):
        side=self.position["side"]
        qty=self.position["qty"]
        if side=="long":
            publish_order(self.a,"sell",qty)
            publish_order(self.b,"buy",qty*self.beta)
        else:
            publish_order(self.a,"buy",qty)
            publish_order(self.b,"sell",qty*self.beta)
        self.position=None
