"""Pydantic-модели – единый формат данных внутри бота."""
from __future__ import annotations
from typing import Literal, Optional, List
from datetime import datetime
from pydantic import BaseModel, Field, validator

Side = Literal["buy", "sell"]

class Tick(BaseModel):
    ts:     int    = Field(..., description="epoch-ms Binance T / BingX ts")
    price:  float
    qty:    float
    side:   Side
    src:    str

    @property
    def dt(self) -> datetime:
        return datetime.fromtimestamp(self.ts / 1000)

class Order(BaseModel):
    id:        Optional[str] = None
    side:      Side
    qty:       float
    price:     Optional[float] = None
    status:    str   = "new"
    created_at:int   = Field(default_factory=lambda: int(datetime.now().timestamp()*1000))

class Position(BaseModel):
    avg_price: float = 0
    qty:       float = 0
    side:      Side  = "buy"

class Portfolio(BaseModel):
    symbol:     str
    positions:  List[Position] = []
    realised_pnl: float = 0
