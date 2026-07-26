"""BingX Open API venue adapter for the carry bot (VST demo / mainnet).

Implements the same `Venue` surface as `bybit_venue.BybitVenue`, over BingX's
Open API (spot leg via `/openApi/spot/v1/*`, USDT-M perp leg via
`/openApi/swap/v2/*`).

SAFETY BY DEFAULT:
  * Constructed read-only (`enable_trading=False`): reads work, every ORDER
    method raises until trading is explicitly enabled.
  * `base_url` defaults to the BingX VST demo host (virtual money); mainnet is
    never the default.
  * Order sizes are validated against the instrument's real step / minimum qty
    / minimum notional BEFORE anything is sent (`preflight`), so the bot cannot
    half-open a position because the second leg was rejected.
  * The adapter tracks the base quantity IT bought (`_owned_base`) so an unwind
    never sells coins the user already held in the same wallet.

HONESTY NOTE — NOT YET VALIDATED AGAINST THE LIVE API:
This adapter was written WITHOUT live-network access: the endpoints, parameter
names and response shapes come from the BingX Open API docs and the legacy
clients in this repo, not from observed traffic. It MUST be run against a BingX
VST demo account (read-only first, then one minimal-size round trip) before it
is pointed at real funds. The assumptions most likely to need a small fix on
first run, in rough order of risk:

  1. SPOT MARKET BUY SIZING — we send `quantity` (base units) to
     `/openApi/spot/v1/trade/order`. Some BingX spot builds want
     `quoteOrderQty` for a MARKET BUY and reject base-qty sizing. If the first
     buy is rejected for a missing/invalid quantity, switch to `quoteOrderQty`
     and set `_owned_base` from the fill instead of the request.
  2. SPOT INSTRUMENT LIMITS — `/openApi/spot/v1/common/symbols` is read as
     `data.symbols[]` with `stepSize` / `minQty` / `minNotional`; some versions
     return `data` as a bare list and/or express size limits as a precision
     integer (`quantityPrecision`) instead of a step. Both shapes are handled
     here, but the field NAMES are the guess.
  3. PERP CONTRACT LIMITS — `/openApi/swap/v2/quote/contracts` is read as
     `quantityPrecision` -> lot step, `tradeMinQuantity` -> min qty,
     `tradeMinUSDT` -> min notional. Verify the real minimum notional (commonly
     ~2 USDT) before trusting `preflight`.
  4. POSITION FIELDS — `positionAmt`, `positionSide`, `unrealizedProfit` and
     the posted-margin field (`margin`, falling back to `initialMargin`). If
     BingX's `margin` already nets unrealised PnL, `perp_margin_ratio()`
     double-counts it (conservative: it tops up / unwinds EARLY, never late),
     but it should still be corrected.
  5. PERP WALLET FIELDS — `/openApi/swap/v2/user/balance` is read as
     `data.balance.equity`; it may come back as a bare `data` object or a list.
  6. FUNDING ROWS — `/openApi/swap/v2/user/income` rows are summed on
     `income`; confirm the sign convention (a received funding payment on a
     short must come back POSITIVE).
  7. HEDGE VS ONE-WAY MODE — orders are sent with `positionSide="SHORT"`. A
     one-way-mode account ignores `positionSide`; if it instead ERRORS, drop
     the field (see `_position_side_params`).

The HMAC signing is deterministic and testable offline; venue behaviour must be
validated on BingX VST with small size before any real money.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import time
import urllib.parse
import urllib.request
from decimal import Decimal

from .bybit_venue import PreflightError, floor_to_step, fmt_qty

VST_BASE = "https://open-api-vst.bingx.com"      # demo / virtual money (default)
MAINNET_BASE = "https://open-api.bingx.com"      # real funds — opt in explicitly
_RECV_WINDOW = "30000"   # absorb clock drift
# quote assets checked longest-first so "BTCUSDT" splits before "BTCUSD"
_QUOTES = ("USDT", "USDC", "USD", "BTC", "ETH", "BNB")


def to_bingx_symbol(symbol: str) -> str:
    """Normalise "BTCUSDT" / "btc-usdt" -> "BTC-USDT".

    BingX dashes base and quote; the rest of the bot (and the CLI default)
    speaks Bybit-style "BTCUSDT", so accept either form rather than making the
    caller remember which venue it is talking to.
    """
    s = (symbol or "").strip().upper().replace("_", "-").replace("/", "-")
    if "-" in s:
        return s
    for quote in _QUOTES:
        if s.endswith(quote) and len(s) > len(quote):
            return f"{s[:-len(quote)]}-{quote}"
    return s


def _sign(secret: str, query: str) -> str:
    """HMAC-SHA256 hex digest of the EXACT query string that will be sent."""
    return hmac.new(secret.encode(), query.encode(), hashlib.sha256).hexdigest()


def _norm_step(step: float) -> float:
    """Keep a whole-number lot step an int.

    The shared helpers do `Decimal(str(step))`, and `str(1.0) == "1.0"` would
    quantize to one decimal — silently permitting 0.1 lots on an instrument
    that only trades whole units. `str(1) == "1"` floors correctly.
    """
    f = float(step)
    return int(f) if f >= 1 and f.is_integer() else f


def _step_from_precision(precision: int) -> float:
    """Decimal places -> lot step (4 -> 0.0001). BingX reports precision, the
    shared helpers want a step."""
    p = max(0, int(precision))
    return _norm_step(float(Decimal(1).scaleb(-p)))


class BingXTradingDisabled(RuntimeError):
    pass


class BingXVenue:
    name = "bingx"

    def __init__(self, api_key: str, api_secret: str, symbol: str = "BTC-USDT",
                 base_url: str = VST_BASE, enable_trading: bool = False,
                 leverage: float = 1.0, timeout: int = 20):
        self.api_key = api_key
        self.api_secret = api_secret
        self.symbol = to_bingx_symbol(symbol)   # callers may pass either form
        self.base_url = base_url.rstrip("/")
        self.enable_trading = bool(enable_trading)
        self.leverage = leverage
        self.timeout = timeout
        self._last_mark = 0.0
        self._instr: dict = {}          # cached instrument limits per category
        self._owned_base = 0.0          # base qty THIS bot bought (never the user's)
        self.funding_collected = 0.0    # quote-currency funding booked since start
        self._funding_since_ms = int(time.time() * 1000)

    @property
    def base_coin(self) -> str:
        return self.symbol.split("-")[0]

    @property
    def quote_coin(self) -> str:
        parts = self.symbol.split("-")
        return parts[1] if len(parts) > 1 else "USDT"

    # ---- transport ----
    def _request(self, method: str, path: str, params: dict, auth: bool) -> dict:
        """One signing path for every call.

        BingX signs the query string; the signature is only valid if the signed
        bytes are IDENTICAL to the bytes on the wire, so the encoded string is
        built ONCE here and reused verbatim (the classic BingX bug is signing a
        raw dict repr and sending a re-encoded one). POST parameters also go in
        the query string with an empty body, for the same reason.
        """
        method = method.upper()
        params = dict(params or {})
        if auth:
            params["timestamp"] = str(int(time.time() * 1000))
            params["recvWindow"] = _RECV_WINDOW
        query = urllib.parse.urlencode(sorted(params.items()))
        headers = {"Content-Type": "application/json"}
        if auth:
            headers["X-BX-APIKEY"] = self.api_key
            # signature is appended AFTER signing and is not itself signed
            query = f"{query}&signature={_sign(self.api_secret, query)}"
        url = f"{self.base_url}{path}"
        if query:
            url = f"{url}?{query}"
        req = urllib.request.Request(url, data=None, headers=headers, method=method)
        with urllib.request.urlopen(req, timeout=self.timeout) as resp:  # noqa: S310
            payload = json.loads(resp.read().decode())
        code = payload.get("code")
        if str(code) not in ("0", "200", "None"):
            raise RuntimeError(f"BingX {path} error: {payload.get('msg')} ({code})")
        data = payload.get("data")
        return payload if data is None else data

    def _require_trading(self) -> None:
        if not self.enable_trading:
            raise BingXTradingDisabled(
                "trading disabled: construct BingXVenue(enable_trading=True) to place orders")

    def _position_side_params(self, side: str) -> dict:
        """Hedge-mode position side. A one-way-mode account ignores
        `positionSide`; only drop this if the account actually errors on it."""
        return {"positionSide": side}

    # ---- instrument limits ----
    def instrument(self, category: str) -> dict:
        """qty step / min qty / min notional for this symbol, cached.

        `category` mirrors the Bybit adapter: "spot" or "linear" (the USDT-M
        swap), so preflight()/live.py can stay venue-agnostic.
        """
        if category in self._instr:
            return self._instr[category]
        out = self._spot_limits() if category == "spot" else self._perp_limits()
        self._instr[category] = out
        return out

    def _spot_limits(self) -> dict:
        data = self._request("GET", "/openApi/spot/v1/common/symbols",
                             {"symbol": self.symbol}, auth=False)
        rows = data.get("symbols") if isinstance(data, dict) else data
        info = self._match_symbol(rows or [])
        if not info:
            raise PreflightError(f"instrument {self.symbol} not found on spot")
        step = _norm_step(info.get("stepSize") or 0.0)
        if step <= 0:   # some builds report precision instead of a step
            step = _step_from_precision(info.get("quantityPrecision") or 6)
        return {
            "qty_step": step,
            "min_qty": float(info.get("minQty") or 0.0),
            "min_notional": float(info.get("minNotional") or 0.0),
        }

    def _perp_limits(self) -> dict:
        # the endpoint may ignore the symbol filter and return every contract
        data = self._request("GET", "/openApi/swap/v2/quote/contracts",
                             {"symbol": self.symbol}, auth=False)
        rows = data if isinstance(data, list) else (data.get("contracts") or [])
        info = self._match_symbol(rows)
        if not info:
            raise PreflightError(f"instrument {self.symbol} not found on linear")
        step = _norm_step(info.get("stepSize") or 0.0)
        if step <= 0:
            step = _step_from_precision(info.get("quantityPrecision") or 4)
        return {
            "qty_step": step,
            "min_qty": float(info.get("tradeMinQuantity") or info.get("minQty") or 0.0),
            "min_notional": float(info.get("tradeMinUSDT") or info.get("minNotional") or 0.0),
        }

    def _match_symbol(self, rows: list) -> dict:
        for row in rows:
            if isinstance(row, dict) and to_bingx_symbol(str(row.get("symbol") or "")) == self.symbol:
                return row
        return {}

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
                    f"{category}: qty {raw_qty:.10g} < min qty {instr['min_qty']:g} "
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
        """Public mark price + private USDT balance. Places NO orders.

        BingX keeps the spot and perp wallets SEPARATE, so `usdt_balance` is the
        sum of both; the per-wallet figures are returned too because a caller
        comparing the sum against "spot notional + perp margin" can still be
        short on one side. Transfers between the two wallets are out of scope
        for this adapter — fund both.
        """
        mark = self.mark_price()
        spot_usdt = self._spot_balances().get(self.quote_coin, 0.0)
        perp_usdt = self._perp_wallet().get("balance", 0.0)
        return {"mark_price": mark, "usdt_balance": spot_usdt + perp_usdt,
                "base_url": self.base_url,
                "spot_usdt": spot_usdt, "perp_usdt": perp_usdt}

    # ---- Venue API ----
    def mark_price(self) -> float:
        data = self._request("GET", "/openApi/swap/v2/quote/price",
                             {"symbol": self.symbol}, auth=False)
        row = data[0] if isinstance(data, list) and data else data
        if isinstance(row, dict):
            px = float(row.get("price") or row.get("markPrice") or 0.0)
            if px > 0:
                self._last_mark = px
        return self._last_mark

    def buy_spot(self, notional: float) -> None:
        self._require_trading()
        instr = self.instrument("spot")
        px = self.mark_price()
        qty = floor_to_step(notional / max(px, 1e-12), instr["qty_step"])
        if qty <= 0 or qty < instr["min_qty"]:
            raise PreflightError(f"spot buy qty {qty} below minimum {instr['min_qty']}")
        # buy an exact BASE quantity so both legs match; quote-sized buys
        # (quoteOrderQty) leave a fee-sized hedge mismatch
        res = self._request("POST", "/openApi/spot/v1/trade/order", {
            "symbol": self.symbol, "side": "BUY", "type": "MARKET",
            "quantity": fmt_qty(qty, instr["qty_step"]),
        }, auth=True)
        # credit only what actually filled when BingX reports it — never claim
        # to own more base than the exchange says we bought
        self._owned_base += self._filled_qty(res, qty)

    def _filled_qty(self, res: dict, requested: float) -> float:
        row = res.get("order") if isinstance(res, dict) and isinstance(res.get("order"), dict) else res
        if isinstance(row, dict):
            filled = float(row.get("executedQty") or row.get("origQty") or 0.0)
            if filled > 0:
                return min(filled, requested)
        return requested

    def sell_spot_qty(self, qty: float) -> None:
        self._require_trading()
        instr = self.instrument("spot")
        qty = floor_to_step(min(qty, self._owned_base), instr["qty_step"])
        if qty <= 0:
            return
        self._request("POST", "/openApi/spot/v1/trade/order", {
            "symbol": self.symbol, "side": "SELL", "type": "MARKET",
            "quantity": fmt_qty(qty, instr["qty_step"]),
        }, auth=True)
        self._owned_base = max(0.0, self._owned_base - qty)

    def open_short_perp(self, notional: float, leverage: float) -> None:
        self._require_trading()
        instr = self.instrument("linear")
        self.set_leverage(leverage)
        qty = floor_to_step(notional / max(self.mark_price(), 1e-12), instr["qty_step"])
        if qty <= 0 or qty < instr["min_qty"]:
            raise PreflightError(f"perp qty {qty} below min qty {instr['min_qty']}")
        params = {"symbol": self.symbol, "side": "SELL", "type": "MARKET",
                  "quantity": fmt_qty(qty, instr["qty_step"])}
        params.update(self._position_side_params("SHORT"))
        self._request("POST", "/openApi/swap/v2/trade/order", params, auth=True)

    def reduce_short_perp_qty(self, qty: float) -> None:
        self._require_trading()
        instr = self.instrument("linear")
        qty = floor_to_step(min(qty, self.perp_short_qty()), instr["qty_step"])
        if qty <= 0:
            return
        # closing a SHORT is a BUY that keeps positionSide=SHORT; reduceOnly
        # guarantees it can never flip the position long
        params = {"symbol": self.symbol, "side": "BUY", "type": "MARKET",
                  "quantity": fmt_qty(qty, instr["qty_step"]), "reduceOnly": "true"}
        params.update(self._position_side_params("SHORT"))
        self._request("POST", "/openApi/swap/v2/trade/order", params, auth=True)

    def set_leverage(self, leverage: float) -> None:
        self._require_trading()
        lev = str(int(round(leverage)))     # BingX takes an integer multiplier
        last: Exception | None = None
        # hedge mode wants the position side, one-way mode wants BOTH
        for side in ("SHORT", "BOTH"):
            try:
                self._request("POST", "/openApi/swap/v2/trade/leverage", {
                    "symbol": self.symbol, "side": side, "leverage": lev,
                }, auth=True)
                return
            except RuntimeError as exc:
                if "not modified" in str(exc).lower():   # already at this leverage
                    return
                last = exc
        if last:
            raise last

    def ensure_isolated(self, leverage: float) -> None:
        """Switch the perp symbol to ISOLATED margin so add-margin top-ups work.

        BingX rejects the switch when a position is already open, which is fine:
        the near-liquidation unwind is the backstop in that case. Best effort —
        the caller logs and continues.
        """
        self._require_trading()
        self._request("POST", "/openApi/swap/v2/trade/marginType", {
            "symbol": self.symbol, "marginType": "ISOLATED",
        }, auth=True)
        self.set_leverage(leverage)

    def add_perp_margin(self, amount: float) -> None:
        self._require_trading()
        if amount <= 0:
            return
        # type=1 adds margin (2 would remove it); requires ISOLATED margin mode
        params = {"symbol": self.symbol, "amount": f"{amount:.4f}", "type": 1}
        params.update(self._position_side_params("SHORT"))
        self._request("POST", "/openApi/swap/v2/trade/positionMargin", params, auth=True)

    def _position(self) -> dict:
        data = self._request("GET", "/openApi/swap/v2/user/positions",
                             {"symbol": self.symbol}, auth=True)
        rows = data if isinstance(data, list) else (data.get("positions") or [])
        for row in rows:
            if not isinstance(row, dict):
                continue
            if to_bingx_symbol(str(row.get("symbol") or "")) != self.symbol:
                continue
            side = str(row.get("positionSide") or "").upper()
            amt = float(row.get("positionAmt") or 0.0)
            # hedge mode: the SHORT leg; one-way mode: a negative amount
            if side == "SHORT" or (side in ("", "BOTH") and amt < 0):
                return row
        return {}

    def _spot_balances(self) -> dict:
        """asset -> total (free + locked) in the SPOT wallet."""
        data = self._request("GET", "/openApi/spot/v1/account/balance", {}, auth=True)
        rows = data.get("balances") if isinstance(data, dict) else data
        out: dict[str, float] = {}
        for row in rows or []:
            if not isinstance(row, dict):
                continue
            asset = str(row.get("asset") or row.get("coin") or "").upper()
            if asset:
                out[asset] = float(row.get("free") or 0.0) + float(row.get("locked") or 0.0)
        return out

    def _perp_wallet(self) -> dict:
        """balance / equity of the USDT-M perp wallet (quote units)."""
        data = self._request("GET", "/openApi/swap/v2/user/balance", {}, auth=True)
        row = data.get("balance") if isinstance(data, dict) else data
        if isinstance(row, list):
            row = next((r for r in row if str(r.get("asset") or "").upper() == self.quote_coin),
                       row[0] if row else {})
        if not isinstance(row, dict):
            return {"balance": 0.0, "equity": 0.0}
        bal = float(row.get("balance") or 0.0)
        return {"balance": bal, "equity": float(row.get("equity") or bal)}

    def wallet_base_qty(self) -> float:
        """Everything of the base coin in the wallet — INCLUDING the user's own
        holdings. Never use this to size a sell."""
        return self._spot_balances().get(self.base_coin, 0.0)

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
        return abs(float(p.get("positionAmt") or 0.0))

    def perp_margin_ratio(self) -> float:
        p = self._position()
        size = abs(float(p.get("positionAmt") or 0.0))
        mark = self.mark_price()
        notional = size * mark
        if notional <= 0:
            return 1.0
        margin = float(p.get("margin") or p.get("initialMargin") or 0.0)
        upnl = float(p.get("unrealizedProfit") or p.get("unrealisedProfit") or 0.0)
        return (margin + upnl) / notional

    def refresh_funding(self) -> float:
        """Sum funding settlements booked since the bot started (quote units).

        BingX records every funding settlement as an income row; summing them is
        the only way to show the user what the carry has actually earned.
        """
        try:
            data = self._request("GET", "/openApi/swap/v2/user/income", {
                "symbol": self.symbol, "incomeType": "FUNDING_FEE",
                "startTime": self._funding_since_ms, "limit": 100,
            }, auth=True)
        except Exception:  # noqa: BLE001 — funding display must never break trading
            return self.funding_collected
        rows = data if isinstance(data, list) else (data.get("income") or [])
        total = 0.0
        for row in rows:
            if not isinstance(row, dict):
                continue
            sym = row.get("symbol")
            if sym and to_bingx_symbol(str(sym)) != self.symbol:
                continue
            total += float(row.get("income") or 0.0)
        self.funding_collected = total
        return total

    def equity(self) -> float:
        """Account equity across BOTH wallets (quote units).

        The perp wallet alone would swing with the short's unrealised PnL while
        the offsetting spot leg sits in another wallet — the drawdown
        kill-switch would then fire on a purely hedged move. So the spot side is
        marked to market and added.
        """
        total = self._perp_wallet().get("equity", 0.0)
        spot = self._spot_balances()
        total += spot.get(self.quote_coin, 0.0)
        base = spot.get(self.base_coin, 0.0)
        if base > 0:
            total += base * self.mark_price()
        return total
