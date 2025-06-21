"""Domain models used inside the bot."""
from __future__ import annotations
from typing import Literal
from pydantic import BaseModel, Field


class Tick(BaseModel):
    ts:    int
    price: float
    qty:   float
    side:  Literal["buy", "sell"]
    src:   str


class Position(BaseModel):
    symbol:   str
    entry:    float
    qty:      float
    side:     Literal["long", "short"]
    unreal_pnl: float = Field(0, description="Will be updated in real-time")


class Order(BaseModel):
    symbol: str
    order_id: int | str
    side:    str
    type:    str
    price:   float
    qty:     float
    status:  str
