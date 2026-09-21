"""Konfigurasi terpusat, dibaca dari environment / file .env.

Semua modul lain mengimpor `settings` dari sini, sehingga tidak ada yang
membaca os.environ langsung.
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


def _split_csv(value: str | list[str] | None) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(v).strip() for v in value if str(v).strip()]
    return [v.strip() for v in str(value).split(",") if v.strip()]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    # Umum
    timezone: str = "Asia/Jakarta"
    log_level: str = "INFO"
    data_dir: Path = Path("./data")
    dry_run: bool = False

    watchlist: str = "BBCA,BBRI,TLKM,ASII,ANTM"

    # Sumber data
    market_data_provider: str = "yahoo_relay"
    goapi_key: str = ""
    rti_token: str = ""
    fmp_api_key: str = ""
    twelvedata_key: str = ""
    alphavantage_key: str = ""
    yahoo_relay_url: str = ""
    yahoo_relay_token: str = ""

    # LLM
    llm_provider: str = "anthropic"
    llm_model: str = "auto"          # 'auto' = pilih model gratis (OpenRouter)
    llm_vision_model: str = "auto"
    anthropic_api_key: str = ""
    openrouter_api_key: str = ""

    # Telegram
    telegram_bot_token: str = ""
    telegram_allowed_chat_ids: str = ""

    # Email
    smtp_host: str = "smtp.gmail.com"
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    email_from: str = ""
    email_to: str = ""

    # Strategi (Agent 3)
    atr_period: int = 14
    min_rrr: float = 2.0
    max_stoploss_pct: float = 3.0
    volume_spike_multiplier: float = 2.0
    volume_lookback_days: int = 20
    max_candidates: int = 5

    # Jam bursa (WIB)
    session1_open: str = "09:00"
    session1_close: str = "12:00"
    session2_open: str = "13:30"
    session2_close: str = "15:50"
    monitor_poll_seconds: int = 60

    # --- Derived helpers ---
    @property
    def watchlist_tickers(self) -> list[str]:
        return [t.upper() for t in _split_csv(self.watchlist)]

    @property
    def allowed_chat_ids(self) -> list[int]:
        return [int(c) for c in _split_csv(self.telegram_allowed_chat_ids)]

    @property
    def db_path(self) -> Path:
        return self.data_dir / "trading_agent.db"

    def ensure_dirs(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        (self.data_dir / "reports").mkdir(parents=True, exist_ok=True)


@lru_cache
def get_settings() -> Settings:
    s = Settings()
    s.ensure_dirs()
    return s


settings = get_settings()
