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
    """Data harga via yfinance. Cocok untuk swing/breakout harian.

    Yahoo kerap membatasi laju (HTTP 429) untuk IP data-center/VPS. Provider
    ini menambah retry dengan backoff dan jeda kecil untuk meredamnya. Bila
    tetap sering 429, pertimbangkan provider berbayar (GoAPI/RTI).
    """

    max_retries: int = 3
    backoff_base: float = 2.0  # detik: 2, 4, 8...

    def _retry(self, fn, what: str, ticker: str):
        import time

        last_exc: Exception | None = None
        for attempt in range(self.max_retries):
            try:
                return fn()
            except Exception as exc:  # noqa: BLE001
                last_exc = exc
                is_rate = "429" in str(exc) or "Too Many Requests" in str(exc)
                if attempt < self.max_retries - 1 and is_rate:
                    wait = self.backoff_base * (2 ** attempt)
                    log.warning("%s %s kena rate-limit, coba lagi dalam %.0fs.", what, ticker, wait)
                    time.sleep(wait)
                    continue
                break
        log.warning("%s %s gagal: %s", what, ticker, last_exc)
        return None

    def history(self, ticker: str, period: str = "3mo", interval: str = "1d"):
        import pandas as pd
        import yfinance as yf

        def _fetch():
            return yf.Ticker(to_yahoo(ticker)).history(period=period, interval=interval)

        df = self._retry(_fetch, "history", ticker)
        return df if df is not None else pd.DataFrame()

    def last_price(self, ticker: str) -> float | None:
        import yfinance as yf

        def _fetch():
            fi = yf.Ticker(to_yahoo(ticker)).fast_info
            price = fi.get("last_price") if hasattr(fi, "get") else fi["lastPrice"]
            return float(price) if price else None

        return self._retry(_fetch, "last_price", ticker)


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
