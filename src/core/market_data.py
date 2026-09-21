"""Adapter data pasar — antarmuka tunggal, implementasi pluggable.

Default: yfinance (gratis, delay ~15 menit). Untuk realtime akurat, buat
adapter GoAPI/RTI dengan mengimplementasikan protokol yang sama lalu
daftarkan di `get_provider()`.

Semua fungsi mengembalikan struktur sederhana (dict / pandas.DataFrame),
sehingga agent tidak bergantung pada detail vendor.
"""
from __future__ import annotations

from typing import Protocol

from src.config import settings
from src.core.logging_conf import get_logger

log = get_logger(__name__)


def to_yahoo(ticker: str) -> str:
    """Ubah kode IDX (mis. 'BBCA') menjadi simbol Yahoo ('BBCA.JK')."""
    t = ticker.upper()
    return t if t.endswith(".JK") else f"{t}.JK"


class MarketDataProvider(Protocol):
    def history(self, ticker: str, period: str = "3mo", interval: str = "1d"): ...
    def last_price(self, ticker: str) -> float | None: ...


class YFinanceProvider:
    """Data harga via yfinance. Cocok untuk swing/breakout harian."""

    def history(self, ticker: str, period: str = "3mo", interval: str = "1d"):
        import yfinance as yf

        df = yf.Ticker(to_yahoo(ticker)).history(period=period, interval=interval)
        return df

    def last_price(self, ticker: str) -> float | None:
        try:
            import yfinance as yf

            fi = yf.Ticker(to_yahoo(ticker)).fast_info
            price = fi.get("last_price") if hasattr(fi, "get") else fi["lastPrice"]
            return float(price) if price else None
        except Exception as exc:  # noqa: BLE001
            log.debug("last_price gagal untuk %s: %s", ticker, exc)
            return None


class NullProvider:
    """Fallback jika provider tidak dikenal — tidak mengembalikan data."""

    def history(self, ticker: str, period: str = "3mo", interval: str = "1d"):
        import pandas as pd

        return pd.DataFrame()

    def last_price(self, ticker: str) -> float | None:
        return None


def get_provider() -> MarketDataProvider:
    name = settings.market_data_provider.lower()
    if name == "yfinance":
        return YFinanceProvider()
    # TODO: tambahkan GoAPIProvider / RTIProvider di sini untuk realtime.
    log.warning("Provider '%s' belum diimplementasikan — memakai NullProvider.", name)
    return NullProvider()
