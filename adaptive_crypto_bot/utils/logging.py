"""Единая настройкаstructured-logging по всему приложению."""
from __future__ import annotations
import logging, sys
from typing import Literal

_LEVELS: dict[str, int] = {
    "TRACE": 5, "DEBUG": 10, "INFO": 20,
    "WARNING": 30, "ERROR": 40, "CRITICAL": 50,
}
logging.addLevelName(5, "TRACE")                 # type: ignore[arg-type]

def _add_trace() -> None:
    def trace(self: logging.Logger, msg, *a, **kw):  # noqa: ANN001
        if self.isEnabledFor(5):
            self._log(5, msg, a, **kw)          # type: ignore[attr-defined]
    logging.Logger.trace = trace                # type: ignore[misc]

_add_trace()

def setup(level: Literal[*_LEVELS.keys(), int] = "INFO") -> logging.Logger:
    lvl = _LEVELS.get(str(level).upper(), int(level))
    fmt = "[%(asctime)s] %(levelname)-8s %(name)s | %(message)s"
    logging.basicConfig(stream=sys.stdout, level=lvl,
                        format=fmt, datefmt="%H:%M:%S", force=True)
    return logging.getLogger("bot")
