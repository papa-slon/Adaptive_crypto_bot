"""Bybit V5 venue adapter for the carry bot (Demo / Testnet / mainnet).

Implements the `Venue` surface the bot uses, over Bybit's V5 REST API (unified
account: spot leg + linear-perp leg).

SAFETY BY DEFAULT:
  * Constructed read-only (`enable_trading=False`): reads work, every ORDER
    method raises until trading is explicitly enabled.
  * `base_url` defaults to Bybit DEMO (paper money); mainnet is never default.
  * Order sizes are validated against the instrument's real qtyStep /
    minOrderQty / minNotional BEFORE anything is sent (`preflight`), so the bot
    cannot half-open a position because the second leg was rejected.
  * The adapter tracks the base quantity IT bought (`_owned_base`) so an unwind
    never sells coins the user already held in the same wallet.

The HMAC signing is unit-tested offline; venue behaviour must be validated on
Bybit Demo with small size before any real money.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import time
import urllib.parse
import urllib.request
from decimal import ROUND_DOWN, Decimal

DEMO_BASE = "https://api-demo.bybit.com"
TESTNET_BASE = "https://api-testnet.bybit.com"
MAINNET_BASE = "https://api.bybit.com"
_RECV_WINDOW = "30000"   # absorb clock drift


def _sign(secret: str, timestamp: str, api_key: str, body_str: str) -> str:
    payload = f"{timestamp}{api_key}{_RECV_WINDOW}{body_str}"
    return hmac.new(secret.encode(), payload.encode(), hashlib.sha256).hexdigest()


def floor_to_step(qty: float, step: float) -> float:
    """Floor a quantity to the instrument's lot step (never round UP: rounding
    up can exceed balance or break the hedge ratio)."""
    if step <= 0:
        return float(qty)
    q = Decimal(str(qty)).quantize(Decimal(str(step)), rounding=ROUND_DOWN)
    return float(q)


def fmt_qty(qty: float, step: float) -> str:
    """Format a quantity with exactly the instrument's decimal precision."""
    d = Decimal(str(step)).normalize()
    decimals = max(0, -d.as_tuple().exponent)
    return f"{qty:.{decimals}f}"


class BybitTradingDisabled(RuntimeError):
    pass


class PreflightError(RuntimeError):
    """Raised when the requested size cannot be traded on this instrument."""


class BybitVenue:
    name = "bybit"

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
        self._instr: dict = {}          # cached instrument limits per category
        self._owned_base = 0.0          # base qty THIS bot bought (never the user's)
        self.funding_collected = 0.0    # quote-currency funding booked since start
        self._funding_since_ms = int(time.time() * 1000)

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

    # ---- instrument limits ----
    def instrument(self, category: str) -> dict:
        """qtyStep / minOrderQty / minNotional for this symbol, cached."""
        if category in self._instr:
            return self._instr[category]
        res = self._request("GET", "/v5/market/instruments-info",
                            {"category": category, "symbol": self.symbol}, auth=False)
        lst = res.get("list") or []
        if not lst:
            raise PreflightError(f"instrument {self.symbol} not found on {category}")
        info = lst[0]
        lot = info.get("lotSizeFilter", {})
        if category == "spot":
            out = {
                "qty_step": float(lot.get("basePrecision") or 0.000001),
                "min_qty": float(lot.get("minOrderQty") or 0.0),
                "min_notional": float(lot.get("minOrderAmt") or 0.0),
            }
        else:
            out = {
                "qty_step": float(lot.get("qtyStep") or 0.001),
                "min_qty": float(lot.get("minOrderQty") or 0.0),
                "min_notional": float(lot.get("minNotionalValue") or 0.0),
            }
        self._instr[category] = out
        return out

    def preflight(self, notional: float, leverage: float) -> dict:
        """Verify BOTH legs are tradeable at this size BEFORE any order is sent.

        Raises PreflightError with an actionable message (including the minimum
        notional that WOULD work) instead of letting the exchange reject the
        second leg and strand an unhedged first leg.
        """
        px = self.mark_price()
        if px <= 0:
            raise PreflightError("no mark price available")
        problems = []
        needed = []
        for category in ("spot", "linear"):
            instr = self.instrument(category)
            raw_qty = notional / px
            qty = floor_to_step(raw_qty, instr["qty_step"])
            if qty <= 0 or qty < instr["min_qty"]:
                min_notional_for_qty = max(instr["min_qty"], instr["qty_step"]) * px
                needed.append(min_notional_for_qty)
                problems.append(
                    f"{category}: qty {raw_qty:.10g} < minOrderQty {instr['min_qty']:g} "
                    f"(needs >= {min_notional_for_qty:.2f} USDT)")
            if instr["min_notional"] and notional < instr["min_notional"]:
                needed.append(instr["min_notional"])
                problems.append(
                    f"{category}: notional {notional:.2f} < min {instr['min_notional']:.2f} USDT")
        if problems:
            raise PreflightError(
                f"{self.symbol} cannot be traded at notional {notional:.2f} USDT — "
                + "; ".join(problems)
                + f". Use at least ~{max(needed) * 1.05:.2f} USDT per leg, or pick a cheaper symbol.")
        return {"ok": True, "price": px,
                "spot": self.instrument("spot"), "linear": self.instrument("linear")}

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
        instr = self.instrument("spot")
        px = self.mark_price()
        qty = floor_to_step(notional / px, instr["qty_step"])
        if qty <= 0 or qty < instr["min_qty"]:
            raise PreflightError(f"spot buy qty {qty} below minimum {instr['min_qty']}")
        # buy an exact BASE quantity so both legs match; quoteCoin sizing would
        # leave a fee-sized hedge mismatch
        self._request("POST", "/v5/order/create", {
            "category": "spot", "symbol": self.symbol, "side": "Buy",
            "orderType": "Market", "qty": fmt_qty(qty, instr["qty_step"]),
            "marketUnit": "baseCoin",
        }, auth=True)
        self._owned_base += qty

    def sell_spot_qty(self, qty: float) -> None:
        self._require_trading()
        instr = self.instrument("spot")
        qty = floor_to_step(min(qty, self._owned_base), instr["qty_step"])
        if qty <= 0:
            return
        self._request("POST", "/v5/order/create", {
            "category": "spot", "symbol": self.symbol, "side": "Sell",
            "orderType": "Market", "qty": fmt_qty(qty, instr["qty_step"]),
            "marketUnit": "baseCoin",
        }, auth=True)
        self._owned_base = max(0.0, self._owned_base - qty)

    def open_short_perp(self, notional: float, leverage: float) -> None:
        self._require_trading()
        instr = self.instrument("linear")
        self.set_leverage(leverage)
        qty = floor_to_step(notional / max(self.mark_price(), 1e-12), instr["qty_step"])
        if qty <= 0 or qty < instr["min_qty"]:
            raise PreflightError(f"perp qty {qty} below minOrderQty {instr['min_qty']}")
        self._request("POST", "/v5/order/create", {
            "category": "linear", "symbol": self.symbol, "side": "Sell",
            "orderType": "Market", "qty": fmt_qty(qty, instr["qty_step"]),
            "reduceOnly": False,
        }, auth=True)

    def reduce_short_perp_qty(self, qty: float) -> None:
        self._require_trading()
        instr = self.instrument("linear")
        qty = floor_to_step(min(qty, self.perp_short_qty()), instr["qty_step"])
        if qty <= 0:
            return
        self._request("POST", "/v5/order/create", {
            "category": "linear", "symbol": self.symbol, "side": "Buy",
            "orderType": "Market", "qty": fmt_qty(qty, instr["qty_step"]),
            "reduceOnly": True,
        }, auth=True)

    def set_leverage(self, leverage: float) -> None:
        self._require_trading()
        try:
            self._request("POST", "/v5/position/set-leverage", {
                "category": "linear", "symbol": self.symbol,
                "buyLeverage": f"{leverage}", "sellLeverage": f"{leverage}",
            }, auth=True)
        except RuntimeError as exc:
            if "110043" not in str(exc):   # "leverage not modified" is fine
                raise

    def ensure_isolated(self, leverage: float) -> None:
        """Switch the perp symbol to ISOLATED margin so add-margin top-ups work.

        Bybit rejects the switch when a position is already open, which is fine:
        the near-liquidation unwind is the backstop in that case.
        """
        self._require_trading()
        self._request("POST", "/v5/position/switch-isolated", {
            "category": "linear", "symbol": self.symbol, "tradeMode": 1,
            "buyLeverage": f"{leverage}", "sellLeverage": f"{leverage}",
        }, auth=True)

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

    def wallet_base_qty(self) -> float:
        """Everything of the base coin in the wallet — INCLUDING the user's own
        holdings. Never use this to size a sell."""
        bal = self._request("GET", "/v5/account/wallet-balance",
                            {"accountType": "UNIFIED"}, auth=True)
        base = self.symbol.replace("USDT", "")
        for acct in bal.get("list", []):
            for c in acct.get("coin", []):
                if c.get("coin") == base:
                    return float(c.get("walletBalance") or 0.0)
        return 0.0

    def spot_base_qty(self) -> float:
        """Only what THIS bot bought — so an unwind can never sell the user's
        pre-existing coins."""
        return self._owned_base

    def adopt_existing(self) -> dict:
        """After a restart, recover state instead of opening a second position.

        Returns the live perp short size and assumes the matching spot leg is
        already held (the bot only ever buys spot to hedge a short it opens).
        """
        qty = self.perp_short_qty()
        if qty > 0:
            self._owned_base = min(qty, self.wallet_base_qty())
        return {"perp_qty": qty, "adopted_spot": self._owned_base}

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

    def refresh_funding(self) -> float:
        """Sum funding settlements booked since the bot started (quote units).

        Bybit records each 8h settlement in the transaction log; summing them is
        the only way to show the user what the carry has actually earned.
        """
        try:
            res = self._request("GET", "/v5/account/transaction-log", {
                "accountType": "UNIFIED", "category": "linear", "currency": "USDT",
                "type": "SETTLEMENT", "startTime": self._funding_since_ms, "limit": 50,
            }, auth=True)
        except Exception:  # noqa: BLE001 — funding display must never break trading
            return self.funding_collected
        total = 0.0
        for row in res.get("list", []):
            if row.get("symbol") and row["symbol"] != self.symbol:
                continue
            total += float(row.get("funding") or row.get("change") or 0.0)
        self.funding_collected = total
        return total

    def equity(self) -> float:
        bal = self._request("GET", "/v5/account/wallet-balance",
                            {"accountType": "UNIFIED"}, auth=True)
        for acct in bal.get("list", []):
            te = acct.get("totalEquity")
            if te is not None:
                return float(te)
        return 0.0
