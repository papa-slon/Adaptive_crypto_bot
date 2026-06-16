from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

import pandas as pd

Action = Literal["long", "short", "flat", "none"]


@dataclass(frozen=True)
class PositionView:
    """Read-only snapshot of the currently held position, passed to `signal`.

    The live loop builds this from the real broker position, so a strategy's
    exit logic is identical in backtest and live.
    """

    side: str          # "long" or "short"
    entry: float
    stop: float
    bars_held: int


@dataclass(frozen=True)
class Signal:
    """A strategy's desired position state at the close of a bar.

    - action "long"/"short": want to be in that direction.
    - action "flat": want no position (exit if held).
    - action "none": no opinion this bar (hold whatever we have).

    `stop` is an ABSOLUTE price the strategy wants the protective stop at.
    The RiskManager turns the stop *distance* into position size. `take_profit`
    is optional; if None the position is managed by stop + strategy exits only.
    """

    action: Action = "none"
    stop: float | None = None
    take_profit: float | None = None
    reason: str = ""
    meta: dict = field(default_factory=dict)


class Strategy:
    """Base class. Subclasses implement `prepare` and `signal`."""

    name: str = "base"

    #: how many leading bars are unusable (indicator warmup)
    warmup: int = 200

    def prepare(self, df: pd.DataFrame) -> pd.DataFrame:
        """Return a COPY of df with indicator columns added (vectorized).

        Must be look-ahead free: column value at row i may only use rows <= i.
        Called once per dataset.
        """
        raise NotImplementedError

    def signal(self, df: pd.DataFrame, i: int, position: "PositionView | None") -> Signal:
        """Decision using the prepared df, at the CLOSE of bar `i`.

        `position` is a PositionView (side / entry / stop / bars_held) when we
        hold something, else None. This lets exit rules be direction- and
        time-aware while the strategy stays otherwise stateless (the live loop
        passes the real broker position, so backtest and live behave the same).

        Only df rows 0..i are valid information. The backtester acts on the
        NEXT bar's open, so this is naturally causal.
        """
        raise NotImplementedError
