
"""Minimal indicator implementations."""
from collections import deque
class EMA:
    def __init__(self, period):
        self.per = period
        self.mult = 2/(period+1)
        self.value = None
    def update(self, price):
        self.value = price if self.value is None else (price-self.value)*self.mult + self.value
        return self.value
class ATR:
    def __init__(self, period):
        self.per = period
        self.trs = deque(maxlen=period)
        self.prev_close=None
    def update(self, bar):
        if self.prev_close is None:
            self.prev_close=bar.close
            return None
        tr = max(bar.high-bar.low, abs(bar.high-self.prev_close), abs(bar.low-self.prev_close))
        self.prev_close=bar.close
        self.trs.append(tr)
        if len(self.trs)<self.per: return None
        return sum(self.trs)/len(self.trs)
