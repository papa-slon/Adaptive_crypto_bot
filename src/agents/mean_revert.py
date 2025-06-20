
import redis, os, typing, math
from core.indicators import EMA, ATR
r = redis.Redis(host=os.getenv("REDIS_HOST","127.0.0.1"), decode_responses=True)

def publish_order(sym, side, qty, stop=None):
    r.xadd("orders:new", {"sym":sym,"side":side,"qty":qty,"stop":stop})

class Bar(typing.NamedTuple):
    ts:int; open:float; high:float; low:float; close:float; vol:float

class MeanRevert:
    """Mean‑reversion agent using Keltner Z‑score and CVD filter."""
    def __init__(self, symbol, risk_pct=0.008):
        self.sym = symbol
        self.ema20 = EMA(20)
        self.atr20 = ATR(20)
        self.position = None
        self.risk_pct = risk_pct
        self.spread_deque = []
    def zscore(self, spread):
        self.spread_deque.append(spread)
        if len(self.spread_deque) > 400:
            self.spread_deque.pop(0)
        if len(self.spread_deque) < 400:
            return None
        mu = sum(self.spread_deque)/len(self.spread_deque)
        sigma = math.sqrt(sum((x-mu)**2 for x in self.spread_deque)/len(self.spread_deque))
        return (spread-mu)/sigma if sigma else 0
    def on_bar(self, bar:Bar, cvd_delta):
        ema = self.ema20.update(bar.close)
        atr = self.atr20.update(bar)
        if None in (ema, atr): return
        spread = bar.close - ema
        z = self.zscore(spread)
        if z is None: return
        # No position yet
        if not self.position and abs(z) > 2 and abs(cvd_delta) < 1.2:
            side = "long" if z < -2 else "short"
            self.open(bar.close, atr, side)
        # Manage
        elif self.position:
            self.manage(bar)
    def open(self, price, atr, side):
        stop = price - 0.8*atr if side=="long" else price + 0.8*atr
        qty = 0.001
        self.position = {"side":side,"entry":price,"stop":stop,"qty":qty,"timeout":30}
        publish_order(self.sym, "buy" if side=="long" else "sell", qty, stop)
    def manage(self, bar:Bar):
        pos = self.position
        pos["timeout"] -=1
        target = pos["entry"] + 0.8*abs(pos["entry"]*0 + 1) if pos["side"]=="long" else pos["entry"] - 0.8
        hit_tp = (bar.high >= target) if pos["side"]=="long" else (bar.low <= target)
        hit_sl = (bar.low <= pos["stop"]) if pos["side"]=="long" else (bar.high >= pos["stop"])
        if hit_tp or hit_sl or pos["timeout"]<=0:
            side = "sell" if pos["side"]=="long" else "buy"
            publish_order(self.sym, side, pos["qty"])
            self.position=None
