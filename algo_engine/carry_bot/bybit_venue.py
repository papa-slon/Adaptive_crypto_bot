"""Bybit V5 venue adapter for the carry bot (Demo / Testnet / mainnet).

Implements the same `Venue` surface the bot uses, over Bybit's V5 REST API
(unified account: spot leg + linear-perp leg). SAFETY BY DEFAULT:

  * Constructed read-only (`enable_trading=False`): mark price, wallet balance,
    and position reads work; every ORDER method raises until trading is
    explicitly enabled. Use `connectivity_check()` to verify keys + funds with
    zero order risk.
  * `base_url` defaults to Bybit DEMO (paper money). Mainnet must be opted into
    explicitly and is never the default.

NOT independently verified against the live venue from this repo's sandbox
(no outbound network). Validate on Bybit Demo with small size + 1x first; the
HMAC signing is unit-tested offline (`../tests/test_bybit_signing.py`).
"""
from __future__ import annotations

import hashlib
import hmac
import json
import time
import urllib.parse
import urllib.request

DEMO_BASE = "https://api-demo.bybit.com"
TESTNET_BASE = "https://api-testnet.bybit.com"
MAINNET_BASE = "https://api.bybit.com"
_RECV_WINDOW = "30000"   # absorb clock drift (same rationale as the sidecar)


def _sign(secret: str, timestamp: str, api_key: str, body_str: str) -> str:
    payload = f"{timestamp}{api_key}{_RECV_WINDOW}{body_str}"
    return hmac.new(secret.encode(), payload.encode(), hashlib.sha256).hexdigest()


class BybitTradingDisabled(RuntimeError):
    pass


class BybitVenue:
    def __init__(self, api_key: str, api_secret: str, symbol: str = "BTCUSDT",
                 base_url: str = DEMO_BASE, enable_trading: bool = False,
                 leverage: float = 1.0, timeout: int = 20):
        self.api_key = api_key
        self.api_secret = api_secret
        self.symbol = symbol
        self.base_url = base_url.rstrip("/")
        self.enable_trading = bool(enable_trading)
        self.leverage = leverage
        self.timeout = timeout
        self._last_mark = 0.0

    # ---- transport ----
    def _request(self, method: str, path: str, params: dict, auth: bool) -> dict:
        method = method.upper()
        url = f"{self.base_url}{path}"
        body_str = ""
        data = None
        headers = {"Content-Type": "application/json"}
        if method == "GET":
            body_str = urllib.parse.urlencode(sorted(params.items())) if params else ""
            if body_str:
                url = f"{url}?{body_str}"
        else:
            body_str = json.dumps(params, separators=(",", ":")) if params else ""
            data = body_str.encode()
        if auth:
            ts = str(int(time.time() * 1000))
            headers.update({
                "X-BAPI-API-KEY": self.api_key,
                "X-BAPI-TIMESTAMP": ts,
                "X-BAPI-RECV-WINDOW": _RECV_WINDOW,
                "X-BAPI-SIGN": _sign(self.api_secret, ts, self.api_key, body_str),
            })
        req = urllib.request.Request(url, data=data, headers=headers, method=method)
        with urllib.request.urlopen(req, timeout=self.timeout) as resp:  # noqa: S310
            payload = json.loads(resp.read().decode())
        if payload.get("retCode") not in (0, None):
            raise RuntimeError(f"Bybit {path} error: {payload.get('retMsg')} ({payload.get('retCode')})")
        return payload.get("result", {})

    def _require_trading(self) -> None:
        if not self.enable_trading:
            raise BybitTradingDisabled(
                "trading disabled: construct BybitVenue(enable_trading=True) to place orders")

    # ---- safe read-only checks ----
    def connectivity_check(self) -> dict:
        """Public mark price + private USDT balance. Places NO orders."""
        mark = self.mark_price()
        bal = self._request("GET", "/v5/account/wallet-balance",
                            {"accountType": "UNIFIED"}, auth=True)
        usdt = 0.0
        for acct in bal.get("list", []):
            for c in acct.get("coin", []):
                if c.get("coin") == "USDT":
                    usdt = float(c.get("walletBalance") or 0.0)
        return {"mark_price": mark, "usdt_balance": usdt, "base_url": self.base_url}

    # ---- Venue API ----
    def mark_price(self) -> float:
        res = self._request("GET", "/v5/market/tickers",
                            {"category": "linear", "symbol": self.symbol}, auth=False)
        lst = res.get("list") or []
        if lst:
            self._last_mark = float(lst[0].get("markPrice") or lst[0].get("lastPrice") or 0.0)
        return self._last_mark

    def buy_spot(self, notional: float) -> None:
        self._require_trading()
        # spot market buy: qty is the QUOTE amount when marketUnit=quoteCoin
        self._request("POST", "/v5/order/create", {
            "category": "spot", "symbol": self.symbol, "side": "Buy",
            "orderType": "Market", "qty": f"{notional}", "marketUnit": "quoteCoin",
        }, auth=True)

    def sell_spot_qty(self, qty: float) -> None:
        self._require_trading()
        self._request("POST", "/v5/order/create", {
            "category": "spot", "symbol": self.symbol, "side": "Sell",
            "orderType": "Market", "qty": f"{qty}", "marketUnit": "baseCoin",
        }, auth=True)

    def open_short_perp(self, notional: float, leverage: float) -> None:
        self._require_trading()
        self.set_leverage(leverage)
        qty = notional / max(self.mark_price(), 1e-9)
        self._request("POST", "/v5/order/create", {
            "category": "linear", "symbol": self.symbol, "side": "Sell",
            "orderType": "Market", "qty": f"{qty:.6f}", "reduceOnly": False,
        }, auth=True)

    def reduce_short_perp_qty(self, qty: float) -> None:
        self._require_trading()
        self._request("POST", "/v5/order/create", {
            "category": "linear", "symbol": self.symbol, "side": "Buy",
            "orderType": "Market", "qty": f"{qty:.6f}", "reduceOnly": True,
        }, auth=True)

    def set_leverage(self, leverage: float) -> None:
        self._require_trading()
        try:
            self._request("POST", "/v5/position/set-leverage", {
                "category": "linear", "symbol": self.symbol,
                "buyLeverage": f"{leverage}", "sellLeverage": f"{leverage}",
            }, auth=True)
        except RuntimeError as exc:
            if "110043" not in str(exc):   # leverage not modified -> fine
                raise

    def add_perp_margin(self, amount: float) -> None:
        self._require_trading()
        if amount <= 0:
            return
        # requires the symbol to be in ISOLATED margin mode
        self._request("POST", "/v5/position/add-margin", {
            "category": "linear", "symbol": self.symbol, "margin": f"{amount:.4f}",
        }, auth=True)

    def _position(self) -> dict:
        res = self._request("GET", "/v5/position/list",
                            {"category": "linear", "symbol": self.symbol}, auth=True)
        lst = res.get("list") or []
        return lst[0] if lst else {}

    def spot_base_qty(self) -> float:
        bal = self._request("GET", "/v5/account/wallet-balance",
                            {"accountType": "UNIFIED"}, auth=True)
        base = self.symbol.replace("USDT", "")
        for acct in bal.get("list", []):
            for c in acct.get("coin", []):
                if c.get("coin") == base:
                    return float(c.get("walletBalance") or 0.0)
        return 0.0

    def perp_short_qty(self) -> float:
        p = self._position()
        return abs(float(p.get("size") or 0.0))

    def perp_margin_ratio(self) -> float:
        p = self._position()
        size = abs(float(p.get("size") or 0.0))
        mark = self.mark_price()
        notional = size * mark
        if notional <= 0:
            return 1.0
        im = float(p.get("positionIM") or 0.0)
        upnl = float(p.get("unrealisedPnl") or 0.0)
        return (im + upnl) / notional

    def equity(self) -> float:
        bal = self._request("GET", "/v5/account/wallet-balance",
                            {"accountType": "UNIFIED"}, auth=True)
        for acct in bal.get("list", []):
            te = acct.get("totalEquity")
            if te is not None:
                return float(te)
        return 0.0
