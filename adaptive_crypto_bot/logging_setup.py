# adaptive_crypto_bot/logging_setup.py
"""Унифицированная настройка логов для консоли и файла.

Используем rich-handler для читаемости, а в production ещё и RotatingFileHandler.
"""

from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

from rich.console import Console
from rich.logging import RichHandler

from .config import get_settings


def setup_logging(level: str | int | None = None) -> None:
    settings = get_settings()
    log_level = (level or settings.LOG_LEVEL).upper()

    # -- базовый формат -------------------------------------------------------
    fmt = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
    datefmt = "%Y-%m-%d %H:%M:%S"

    console_handler = RichHandler(
        console=Console(), markup=True, rich_tracebacks=True, show_path=False
    )

    handlers: list[logging.Handler] = [console_handler]

    # -- файл-логгер только в продакшене -------------------------------------
    if settings.is_prod:
        log_dir = Path("/logs")
        log_dir.mkdir(parents=True, exist_ok=True)
        file_handler = RotatingFileHandler(
            log_dir / "app.log",
            maxBytes=5 * 1024 * 1024,  # 5 MB
            backupCount=3,
            encoding="utf-8",
        )
        file_handler.setFormatter(logging.Formatter(fmt, datefmt))
        handlers.append(file_handler)

    logging.basicConfig(
        level=log_level,
        format=fmt,
        datefmt=datefmt,
        handlers=handlers,
        force=True,  # перезаписать пред. конфиг если был
    )

    # Прятать спам от urllib3 / websockets, если не DEBUG
    if logging.getLogger().level > logging.DEBUG:
        logging.getLogger("urllib3").setLevel(logging.WARNING)
        logging.getLogger("websockets").setLevel(logging.WARNING)

