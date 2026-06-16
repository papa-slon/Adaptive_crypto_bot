"""Bot state persistence for the monitoring dashboard.

The live loop calls `StateWriter.update(snapshot)` each tick. It writes a
current-state JSON (atomic) plus appends an equity point to a JSONL history the
dashboard charts. No external deps.
"""
from __future__ import annotations

import json
import os
import time
from collections import deque
from datetime import datetime, timezone

STATE_PATH = "logs/carry_state.json"
HISTORY_PATH = "logs/carry_history.jsonl"
_MAX_HISTORY = 5000


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def build_snapshot(venue, bot, meta: dict, actions: deque, errors: int,
                   started_at: float) -> dict:
    """Read venue/bot safely into a flat dict the dashboard renders."""
    def safe(fn, default=None):
        try:
            return fn()
        except Exception:  # noqa: BLE001 — a read failure must not break the writer
            return default

    equity = safe(venue.equity)
    start_equity = getattr(bot, "start_equity_snapshot", None)
    funding = getattr(venue, "funding_collected", None)
    snap = {
        "ts": _now_iso(),
        "started_at": datetime.fromtimestamp(started_at, timezone.utc).isoformat(timespec="seconds"),
        "uptime_seconds": int(time.time() - started_at),
        "state": bot.state,
        "mode": meta.get("mode", "paper"),
        "symbol": meta.get("symbol"),
        "notional": meta.get("notional"),
        "leverage": meta.get("leverage"),
        "price": safe(venue.mark_price),
        "perp_qty": safe(venue.perp_short_qty),
        "spot_qty": safe(venue.spot_base_qty),
        "margin_ratio": safe(venue.perp_margin_ratio),
        "equity": equity,
        "start_equity": start_equity,
        "pnl": (equity - start_equity) if (equity is not None and start_equity is not None) else None,
        "funding_collected": funding,
        "errors": errors,
        "actions": list(actions),
    }
    if equity is not None and start_equity:
        snap["pnl_pct"] = (equity / start_equity - 1.0) * 100.0
    return snap


class StateWriter:
    def __init__(self, state_path: str = STATE_PATH, history_path: str = HISTORY_PATH):
        self.state_path = state_path
        self.history_path = history_path
        os.makedirs(os.path.dirname(state_path) or ".", exist_ok=True)

    def update(self, snap: dict) -> None:
        tmp = f"{self.state_path}.tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(snap, f, ensure_ascii=False, indent=2)
        os.replace(tmp, self.state_path)
        if snap.get("equity") is not None:
            with open(self.history_path, "a", encoding="utf-8") as f:
                f.write(json.dumps({"ts": snap["ts"], "equity": snap["equity"],
                                    "price": snap.get("price"),
                                    "margin_ratio": snap.get("margin_ratio")}) + "\n")
            self._trim_history()

    def _trim_history(self) -> None:
        try:
            with open(self.history_path, encoding="utf-8") as f:
                lines = f.readlines()
            if len(lines) > _MAX_HISTORY:
                with open(self.history_path, "w", encoding="utf-8") as f:
                    f.writelines(lines[-_MAX_HISTORY:])
        except FileNotFoundError:
            pass


def read_state(state_path: str = STATE_PATH) -> dict | None:
    try:
        with open(state_path, encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return None


def read_history(history_path: str = HISTORY_PATH, limit: int = 1000) -> list[dict]:
    try:
        with open(history_path, encoding="utf-8") as f:
            lines = f.readlines()[-limit:]
        return [json.loads(x) for x in lines if x.strip()]
    except FileNotFoundError:
        return []
