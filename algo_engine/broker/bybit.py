"""Bybit V5 broker (demo or live) — REST, no third-party SDK.

Only runs when YOU instantiate it with your own API key/secret (read from env
in live.py). It defaults to the DEMO endpoint. Every order is a single market
order with an attached protective stop-loss; sizing is decided upstream by the
RiskManager, never here.

Safety notes baked in:
  * `demo=True` by default -> api-demo.bybit.com. Live requires demo=False
    explicitly AND env AE_ALLOW_LIVE=1 (checked in live.py).
  * qty is floored to the instrument's qtyStep, price to tickSize.
  * decrypted secrets are NEVER logged.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import math
import time
import urllib.parse
import urllib.request

from .base import Broker, BrokerPosition

_DEMO_BASE = "https://api-demo.bybit.com"
_LIVE_BASE = "https://api.bybit.com"
_RECV_WINDOW = "30000"  # absorb clock drift (matches the terminal's sidecar pin)


class BybitBroker(Broker):
    def __init__(
        self,
        api_key: str,
        api_secret: str,
        demo: bool = True,
        category: str = "linear",
        account_type: str = "UNIFIED",
    ) -> None:
        if not api_key or not api_secret:
            raise ValueError("Bybit API key/secret required")
        self._key = api_key
        self._secret = api_secret.encode()
        self.base = _DEMO_BASE if demo else _LIVE_BASE
        self.demo = demo
        self.category = category
        self.account_type = account_type
        self._instr: dict[str, dict] = {}

    # ----- signing / transport ------------------------------------------------
    def _sign(self, ts: str, payload: str) -> str:
        msg = f"{ts}{self._key}{_RECV_WINDOW}{payload}"
        return hmac.new(self._secret, msg.encode(), hashlib.sha256).hexdigest()

    def _request(self, method: str, path: str, params: dict, signed: bool) -> dict:
        ts = str(int(time.time() * 1000))
        headers = {"Content-Type": "application/json"}
        if method == "GET":
            query = urllib.parse.urlencode(params)
            url = f"{self.base}{path}?{query}" if query else f"{self.base}{path}"
            body_bytes = None
            sign_payload = query
        else:
            body = json.dumps(params, separators=(",", ":"))
            url = f"{self.base}{path}"
            body_bytes = body.encode()
            sign_payload = body
        if signed:
            headers.update(
                {
                    "X-BAPI-API-KEY": self._key,
                    "X-BAPI-TIMESTAMP": ts,
                    "X-BAPI-RECV-WINDOW": _RECV_WINDOW,
                    "X-BAPI-SIGN": self._sign(ts, sign_payload),
                }
            )
        req = urllib.request.Request(url, data=body_bytes, headers=headers, method=method)
        with urllib.request.urlopen(req, timeout=20) as resp:  # noqa: S310 (trusted host)
            data = json.loads(resp.read().decode())
        if data.get("retCode") != 0:
            raise RuntimeError(f"Bybit {path} error: {data.get('retMsg')} ({data.get('retCode')})")
        return data["result"]

    # ----- instrument rounding ------------------------------------------------
    def _instrument(self, symbol: str) -> dict:
        if symbol not in self._instr:
            res = self._request(
                "GET",
                "/v5/market/instruments-info",
                {"category": self.category, "symbol": symbol},
                signed=False,
            )
            info = res["list"][0]
            self._instr[symbol] = {
                "qty_step": float(info["lotSizeFilter"]["qtyStep"]),
                "min_qty": float(info["lotSizeFilter"]["minOrderQty"]),
                "tick": float(info["priceFilter"]["tickSize"]),
            }
        return self._instr[symbol]

    @staticmethod
    def _floor_step(value: float, step: float) -> float:
        if step <= 0:
            return value
        return math.floor(value / step) * step

    @staticmethod
    def _round_tick(value: float, tick: float) -> float:
        if tick <= 0:
            return value
        # precision via log10 (never string-based; matches the terminal fix)
        prec = max(0, -int(math.floor(math.log10(tick))))
        return round(round(value / tick) * tick, prec)

    # ----- Broker interface ---------------------------------------------------
    def get_equity(self) -> float:
        res = self._request(
            "GET", "/v5/account/wallet-balance", {"accountType": self.account_type}, signed=True
        )
        rows = res.get("list", [])
        if not rows:
            return 0.0
        return float(rows[0].get("totalEquity") or 0.0)

    def get_last_price(self, symbol: str) -> float:
        res = self._request(
            "GET", "/v5/market/tickers", {"category": self.category, "symbol": symbol}, signed=False
        )
        return float(res["list"][0]["lastPrice"])

    def get_position(self, symbol: str) -> BrokerPosition | None:
        res = self._request(
            "GET", "/v5/position/list", {"category": self.category, "symbol": symbol}, signed=True
        )
        for row in res.get("list", []):
            size = float(row.get("size") or 0.0)
            if size > 0:
                side = "long" if row.get("side") == "Buy" else "short"
                stop_raw = row.get("stopLoss") or 0.0
                return BrokerPosition(
                    symbol=symbol,
                    side=side,
                    qty=size,
                    entry=float(row.get("avgPrice") or 0.0),
                    stop=float(stop_raw) if stop_raw and float(stop_raw) > 0 else None,
                )
        return None

    def open_market(self, symbol: str, side: str, qty: float, stop: float | None = None) -> dict:
        instr = self._instrument(symbol)
        qty = self._floor_step(qty, instr["qty_step"])
        if qty < instr["min_qty"]:
            return {"ok": False, "reason": f"qty {qty} < minOrderQty {instr['min_qty']}"}
        params = {
            "category": self.category,
            "symbol": symbol,
            "side": "Buy" if side == "long" else "Sell",
            "orderType": "Market",
            "qty": _fmt(qty),
            "timeInForce": "IOC",
        }
        if stop is not None and stop > 0:
            params["stopLoss"] = _fmt(self._round_tick(stop, instr["tick"]))
            params["slTriggerBy"] = "MarkPrice"
        res = self._request("POST", "/v5/order/create", params, signed=True)
        return {"ok": True, "orderId": res.get("orderId"), "qty": qty, "side": side}

    def close_market(self, symbol: str) -> dict:
        pos = self.get_position(symbol)
        if pos is None:
            return {"ok": True, "filled": 0.0}
        params = {
            "category": self.category,
            "symbol": symbol,
            "side": "Sell" if pos.side == "long" else "Buy",
            "orderType": "Market",
            "qty": _fmt(pos.qty),
            "reduceOnly": True,
            "timeInForce": "IOC",
        }
        res = self._request("POST", "/v5/order/create", params, signed=True)
        return {"ok": True, "orderId": res.get("orderId"), "filled": pos.qty}

    def name(self) -> str:
        return f"BybitBroker({'demo' if self.demo else 'LIVE'})"


def _fmt(v: float) -> str:
    """Format a number without scientific notation or trailing zeros."""
    return f"{v:.10f}".rstrip("0").rstrip(".")
