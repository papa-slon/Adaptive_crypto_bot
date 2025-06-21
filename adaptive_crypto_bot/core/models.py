"""
Понятия домена: тик, ордер, позиция.
Все схемы – Pydantic v2 (BaseModel) ⇒ валидация + сериализация ''из-коробки''.
"""

from __future__ import annotations

import enum
from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field

# ── биржевые константы ───────────────────────────────────────────────────────────
class Side(str, enum.Enum):
    BUY  = "BUY"
    SELL = "SELL"

class OrderStatus(str, enum.Enum):
    NEW        = "NEW"
    PART_FILLED= "PART_FILLED"
    FILLED     = "FILLED"
    CANCELED   = "CANCELED"
    REJECTED   = "REJECTED"

# ── стрим-тик ────────────────────────────────────────────────────────────────────
class Tick(BaseModel):
    ts:    int          = Field(..., description="Unix-мс биржи")
    price: float        = Field(..., gt=0)
    qty:   float        = Field(..., gt=0)
    side:  Side
    src:   str          = Field(..., description="Код биржи BIN/BGX …")

# ── ордер & позиция ──────────────────────────────────────────────────────────────
class Order(BaseModel):
    order_id:   str
    symbol:     str
    side:       Side
    qty:        float  = Field(..., gt=0)
    price:      float  = Field(..., gt=0)
    status:     OrderStatus
    exchange:   str    = Field(..., description="binance | bingx")
    created_at: datetime

class Position(BaseModel):
    symbol:   str
    qty:      float
    entry_px: float
    side:     Side
