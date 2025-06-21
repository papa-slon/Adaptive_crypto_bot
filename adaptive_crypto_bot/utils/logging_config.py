"""Structured + colored logging across the whole app."""
import logging, sys, json, os
from datetime import datetime
from typing import Any, Dict


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:           # noqa: D401
        data: Dict[str, Any] = {
            "ts":   datetime.utcnow().isoformat(timespec="milliseconds") + "Z",
            "lvl":  record.levelname,
            "msg":  record.getMessage(),
            "name": record.name,
        }
        if record.exc_info:
            data["exc"] = self.formatException(record.exc_info)
        return json.dumps(data, ensure_ascii=False)


def setup_logging(level: str = "INFO") -> None:
    root = logging.getLogger()
    root.setLevel(level)

    # human-friendly console output
    console = logging.StreamHandler(sys.stdout)
    console.setFormatter(logging.Formatter(
        fmt="%(asctime)s %(levelname)-8s %(name)s ▶ %(message)s",
        datefmt="%H:%M:%S",
    ))
    root.addHandler(console)

    # machine-readable json file (rotated daily by logrotate on host)
    if path := os.getenv("LOG_JSON_PATH"):
        file_handler = logging.FileHandler(path)
        file_handler.setFormatter(JsonFormatter())
        root.addHandler(file_handler)
