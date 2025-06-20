
import redis, os, typing, math, collections
from core.indicators import ATR
r = redis.Redis(host=os.getenv("REDIS_HOST","127.0.0.1"), decode_responses=True)

def publish_order(sym, side, qty, stop=None):
    r.xadd("orders:new", {"sym":sym,"side":side,"qty":qty,"stop":stop})

class Bar(typing.NamedTuple):
    ts:int; open:float; high:float; low:float; close:float; vol:float

class VWAPSweep:
    """Detects stop‑hunt wicks against 12‑bar extremum and enters reversal."""
    def __init__(self, symbol, beta=12, risk_pct=0.006):
        self.sym = symbol
        self.beta = beta
        self.highs = collections.deque(maxlen=beta)
        self.lows = collections.deque(maxlen=beta)
        self.position=None
        self.atr14 = ATR(14)
        self.risk_pct=risk_pct
        self.watch=None  # {"side":..., "bars":3}
    def on_bar(self, bar:Bar, cvd_delta, vwap_slope):
        self.highs.append(bar.high); self.lows.append(bar.low)
        atr = self.atr14.update(bar)
        if atr is None: return
        high_n, low_n = max(self.highs), min(self.lows)
        # detect initial sweep
        if not self.position and not self.watch:
            if bar.high > high_n * (1.0001) and vwap_slope > 0:
                self.watch={"side":"long","lvl":high_n,"timeout":3}
            elif bar.low < low_n * (0.9999) and vwap_slope < 0:
                self.watch={"side":"short","lvl":low_n,"timeout":3}
        # handle watch
        if self.watch:
            self.watch["timeout"]-=1
            if self.watch["side"]=="long" and bar.close < self.watch["lvl"] and cvd_delta>1.5:
                self.open(bar.close, atr, "long")
                self.watch=None
            elif self.watch["side"]=="short" and bar.close > self.watch["lvl"] and cvd_delta<-1.5:
                self.open(bar.close, atr, "short"); self.watch=None
            elif self.watch["timeout"]<=0:
                self.watch=None
        elif self.position:
            self.manage(bar, atr)
    def open(self, price, atr, side):
        stop = price-1*atr if side=="long" else price+1*atr
        qty=0.001
        self.position={"side":side,"entry":price,"stop":stop,"half":False}
        publish_order(self.sym, "buy" if side=="long" else "sell", qty, stop)
    def manage(self, bar:Bar, atr):
        pos=self.position
        move=(bar.close-pos["entry"]) if pos["side"]=="long" else (pos["entry"]-bar.close)
        if not pos["half"] and move>=atr:
            qty=pos["qty"]/2
            publish_order(self.sym, "sell" if pos["side"]=="long" else "buy", qty)
            pos["half"]=True
            pos["stop"]=pos["entry"]+0.1*atr if pos["side"]=="long" else pos["entry"]-0.1*atr
            publish_order(self.sym,"modify",pos["qty"]/2,pos["stop"])
        hit_sl=(bar.low<=pos["stop"]) if pos["side"]=="long" else (bar.high>=pos["stop"])
        if hit_sl:
            publish_order(self.sym,"sell" if pos["side"]=="long" else "buy", pos["qty"]/2)
            self.position=None
