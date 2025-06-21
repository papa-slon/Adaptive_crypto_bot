"""Pydantic-схемы и enum-ы, общие для всех бирж."""
from enum import Enum
from pydantic import BaseModel


class OrderSide(str, Enum):
    BUY  = "BUY"
    SELL = "SELL"


class OrderType(str, Enum):
    MARKET = "MARKET"
    LIMIT  = "LIMIT"


class OrderResponse(BaseModel):
    """Унифицированный ответ при создании/отмене ордера."""
    symbol:          str
    orderId:         int | str
    price:           str
    origQty:         str
    executedQty:     str
    status:          str
    type:            str
    side:            str
    clientOrderId:   str | None = None
