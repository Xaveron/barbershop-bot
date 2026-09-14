"""Конфигурация приложения (Pydantic Settings).

Все секреты читаются только из окружения / .env — в коде их нет.
"""

from __future__ import annotations

from functools import lru_cache
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Дублируется в app.bot.i18n.LANGUAGES; здесь — чтобы config не зависел от bot.
SUPPORTED_LANGUAGES: tuple[str, ...] = ("ru", "ro", "en")


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # --- Обязательные -------------------------------------------------------
    bot_token: SecretStr = Field(validation_alias="BOT_TOKEN", min_length=20)
    database_url: str = Field(validation_alias="DATABASE_URL", min_length=10)
    admin_id: str = Field(default="", validation_alias="ADMIN_ID")
    timezone: str = Field(default="Europe/Chisinau", validation_alias="TIMEZONE")

    # --- Логирование --------------------------------------------------------
    log_level: str = "INFO"
    sql_echo: bool = False
    # Адрес локального Bot API server (https://core.telegram.org/bots/api#using-a-local-bot-api-server).
    # Пусто — работаем с официальным api.telegram.org.
    telegram_api_base: str = ""

    # --- Язык и валюта ------------------------------------------------------
    # Язык по умолчанию, если у клиента в Telegram другой язык: ru | ro | en.
    default_language: str = Field(default="ru", validation_alias="DEFAULT_LANGUAGE")
    # Валюта новых услуг; у каждой услуги валюта хранится отдельно.
    default_currency: str = Field(default="MDL", min_length=3, max_length=3)
    # Спрашивать телефон при первой записи (полезно для звонка клиенту).
    require_phone: bool = False

    # --- Бизнес-логика ------------------------------------------------------
    slot_step_minutes: int = Field(default=15, ge=5, le=120)
    booking_horizon_days: int = Field(default=14, ge=1, le=90)
    min_lead_minutes: int = Field(default=60, ge=0, le=10080)
    cancel_min_lead_minutes: int = Field(default=120, ge=0, le=10080)
    max_active_appointments: int = Field(default=3, ge=1, le=20)
    max_slots_per_day: int = Field(default=60, ge=10, le=100)

    # --- Redis (FSM-хранилище) ----------------------------------------------
    # Если задан — FSM-состояния хранятся в Redis (не теряются при перезапуске).
    redis_url: str = Field(default="", validation_alias="REDIS_URL")

    # --- Антифлуд -----------------------------------------------------------
    throttle_interval: float = Field(default=0.4, ge=0.0, le=10.0)
    throttle_burst: int = Field(default=10, ge=1, le=100)

    # --- Контакты барбершопа ------------------------------------------------
    shop_name: str = "Barbershop"
    shop_address: str = "Кишинёв"
    shop_phone: str = "+373 60 000 000"
    shop_maps_url: str = ""

    # --- Валидаторы ---------------------------------------------------------
    @field_validator("default_language")
    @classmethod
    def _validate_language(cls, value: str) -> str:
        language = value.strip().lower()
        if language not in SUPPORTED_LANGUAGES:
            raise ValueError(f"DEFAULT_LANGUAGE должен быть одним из {SUPPORTED_LANGUAGES}")
        return language

    @field_validator("default_currency")
    @classmethod
    def _validate_currency(cls, value: str) -> str:
        currency = value.strip().upper()
        if not currency.isalpha():
            raise ValueError("DEFAULT_CURRENCY — трёхбуквенный код, например MDL, RON, EUR")
        return currency

    @field_validator("database_url")
    @classmethod
    def _ensure_async_driver(cls, value: str) -> str:
        """Приводим DSN к asyncpg-драйверу: приложение работает только асинхронно."""
        if value.startswith("postgresql+asyncpg://"):
            return value
        if value.startswith("postgres://"):
            return value.replace("postgres://", "postgresql+asyncpg://", 1)
        if value.startswith("postgresql://"):
            return value.replace("postgresql://", "postgresql+asyncpg://", 1)
        if value.startswith("postgresql+"):
            raise ValueError("Поддерживается только драйвер asyncpg (postgresql+asyncpg://...)")
        raise ValueError("DATABASE_URL должен быть PostgreSQL DSN")

    @field_validator("timezone")
    @classmethod
    def _validate_timezone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except ZoneInfoNotFoundError as exc:  # pragma: no cover - зависит от системы
            raise ValueError(f"Неизвестный часовой пояс: {value}") from exc
        return value

    @field_validator("log_level")
    @classmethod
    def _validate_log_level(cls, value: str) -> str:
        allowed = {"CRITICAL", "ERROR", "WARNING", "INFO", "DEBUG"}
        upper = value.upper()
        if upper not in allowed:
            raise ValueError(f"LOG_LEVEL должен быть одним из {sorted(allowed)}")
        return upper

    # --- Производные значения ----------------------------------------------
    @property
    def admin_ids(self) -> tuple[int, ...]:
        """ADMIN_ID может содержать несколько id через запятую/точку с запятой."""
        raw = self.admin_id.replace(";", ",").replace(" ", ",")
        return tuple(int(chunk) for chunk in raw.split(",") if chunk.strip().isdigit())

    @property
    def tz(self) -> ZoneInfo:
        return ZoneInfo(self.timezone)

    def is_admin(self, telegram_id: int | None) -> bool:
        return telegram_id is not None and telegram_id in self.admin_ids


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Кешированные настройки (одна инстанция на процесс)."""
    return Settings()  # type: ignore[call-arg]
