
import redis, json, typing, os
from core.indicators import EMA, ATR
r = redis.Redis(host=os.getenv("REDIS_HOST","127.0.0.1"), decode_responses=True)

def publish_order(sym, side, qty, stop=None):
    order = {"sym":sym,"side":side,"qty":qty,"stop":stop}
    r.xadd("orders:new", order)

class Bar(typing.NamedTuple):
    ts:int; open:float; high:float; low:float; close:float; vol:float

class TrendTF:
    def __init__(self, symbol):
        self.sym=symbol
        self.ema21=EMA(21); self.ema200=EMA(200); self.atr=ATR(14)
        self.position=None

    def on_bar(self, bar:Bar):
        f=self.ema21.update(bar.close); s=self.ema200.update(bar.close); a=self.atr.update(bar)
        if None in (f,s,a): return
        if not self.position:
            if f>s: self._open(bar.close,a,"long")
            elif f<s: self._open(bar.close,a,"short")
        else: self._manage(bar,a)

    def _open(self, price, atr, side):
        stop=price-1.2*atr if side=="long" else price+1.2*atr
        qty=0.001  # placeholder
        self.position={"side":side,"entry":price,"stop":stop,"qty":qty}
        publish_order(self.sym, "buy" if side=="long" else "sell", qty, stop)

    def _manage(self, bar, atr):
        pos=self.position
        move=(bar.close-pos["entry"]) if pos["side"]=="long" else (pos["entry"]-bar.close)
        if move>=atr:
            new_stop=bar.close-atr if pos["side"]=="long" else bar.close+atr
            if (pos["side"]=="long" and new_stop>pos["stop"]) or (pos["side"]=="short" and new_stop<pos["stop"]):
                pos["stop"]=new_stop; publish_order(self.sym,"modify",pos["qty"],new_stop)
        if (pos["side"]=="long" and bar.low<=pos["stop"]) or (pos["side"]=="short" and bar.high>=pos["stop"]):
            self.close()
    def close(self):
        side="sell" if self.position["side"]=="long" else "buy"
        publish_order(self.sym, side, self.position["qty"]); self.position=None
