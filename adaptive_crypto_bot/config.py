# adaptive_crypto_bot/config.py
"""Централизованные настройки приложения.

Все параметры берутся из переменных окружения, .env-файла либо аргументов CLI.
Используется Pydantic BaseSettings → значения валидируются и имеют дефолты.
"""

from functools import lru_cache
from pathlib import Path
from typing import Optional

from pydantic import BaseSettings, Field, validator


class Settings(BaseSettings):
    # ─────────────────── infra ───────────────────
    ENV: str = Field("dev", description="dev / prod – влияет на уровень логов и т.д.")
    LOG_LEVEL: str = Field("INFO", description="TRACE | DEBUG | INFO | WARNING | ERROR")

    # Redis
    REDIS_HOST: str = Field("redis", description="Имя сервиса в docker-compose или IP")
    REDIS_PORT: int = Field(6379)
    REDIS_STREAM: str = Field("ticks:core", description="Куда кладём нормализованные тики")

    # Binance API
    BINANCE_API_KEY: str = Field(..., env="BINANCE_API_KEY")
    BINANCE_SECRET: str = Field(..., env="BINANCE_SECRET")

    # BingX API
    BINGX_API_KEY: str = Field(..., env="BINGX_API_KEY")
    BINGX_SECRET: str = Field(..., env="BINGX_SECRET")

    # торговые параметры
    SYMBOL: str = Field("BTCUSDT")
    BASE_ORDER_USDT: float = Field(20, description="Размер первой заявки")
    SAFETY_ORDER_USDT: float = Field(15, description="Размер усредняющей заявки")
    MAX_SLOTS: int = Field(10, description="Максимум одновременно открытых слотов")

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        case_sensitive = False

    # ────── дополнительные валидаторы ──────
    @validator("LOG_LEVEL")
    def _level_upper(cls, v: str) -> str:
        return v.upper()

    @property
    def redis_dsn(self) -> str:
        return f"redis://{self.REDIS_HOST}:{self.REDIS_PORT}"

    @property
    def is_prod(self) -> bool:
        return self.ENV.lower() == "prod"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Кэшируем инстанс, чтобы не создавать его в каждом модуле."""
    return Settings()


# ──────────────────────────────────────────────────────────────────────────────
@lru_cache
def get_settings() -> "Settings":          # 1 экз. на процесс
    return Settings()

# удобная «сейчас» для тайм-стемпов
def now() -> int:
    return int(time.time()*1000)
