"""Adapter data pasar — antarmuka tunggal, implementasi pluggable.

Provider (pilih via MARKET_DATA_PROVIDER di .env):
  - yahoo_direct : REKOMENDASI utk VPS. Endpoint chart Yahoo langsung dengan
                   browser-impersonation (curl_cffi) — sering lolos blokir 429
                   yang menimpa yfinance di IP data-center. Gratis, tanpa key.
  - yfinance     : Library yfinance (mudah kena 429 di VPS). Kini juga memakai
                   sesi curl_cffi bila tersedia.
  - fmp          : Financial Modeling Prep (butuh FMP_API_KEY gratis).
  - goapi / rti  : placeholder untuk provider berbayar realtime.

Semua fungsi mengembalikan pandas.DataFrame (kolom Open/High/Low/Close/Volume)
atau float, sehingga agent tidak bergantung pada detail vendor.
"""
from __future__ import annotations

from typing import Protocol

from src.config import settings
from src.core.logging_conf import get_logger

log = get_logger(__name__)

# Range Yahoo yang valid untuk parameter chart API.
_YF_RANGES = {"1d", "5d", "1mo", "3mo", "6mo", "1y", "2y", "5y", "10y", "ytd", "max"}


def to_yahoo(ticker: str) -> str:
    """Ubah kode IDX (mis. 'BBCA') menjadi simbol Yahoo ('BBCA.JK')."""
    t = ticker.upper()
    return t if t.endswith(".JK") else f"{t}.JK"


def _http_get_json(url: str, params: dict, timeout: int = 30):
    """GET JSON dengan browser-impersonation bila curl_cffi ada, else requests."""
    try:
        from curl_cffi import requests as creq

        r = creq.get(url, params=params, impersonate="chrome", timeout=timeout)
    except ImportError:
        import requests

        ua = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
              "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"}
        r = requests.get(url, params=params, headers=ua, timeout=timeout)
    r.raise_for_status()
    return r.json()


class MarketDataProvider(Protocol):
    def history(self, ticker: str, period: str = "3mo", interval: str = "1d"): ...
    def last_price(self, ticker: str) -> float | None: ...


class YahooDirectProvider:
    """Akses langsung endpoint chart Yahoo Finance via curl_cffi.

    Meniru header & TLS fingerprint browser sehingga lebih tahan terhadap
    blokir 429 yang menimpa yfinance di IP VPS. Tanpa API key.
    """

    CHART_URL = "https://query1.finance.yahoo.com/v8/finance/chart/"

    def _fetch(self, ticker: str, rng: str, interval: str):
        url = self.CHART_URL + to_yahoo(ticker)
        return _http_get_json(url, {"range": rng, "interval": interval})

    def history(self, ticker: str, period: str = "3mo", interval: str = "1d"):
        import pandas as pd

        rng = period if period in _YF_RANGES else "3mo"
        try:
            data = self._fetch(ticker, rng, interval)
            result = data["chart"]["result"][0]
            ts = result.get("timestamp") or []
            q = result["indicators"]["quote"][0]
            df = pd.DataFrame(
                {
                    "Open": q.get("open"),
                    "High": q.get("high"),
                    "Low": q.get("low"),
                    "Close": q.get("close"),
                    "Volume": q.get("volume"),
                },
                index=pd.to_datetime(ts, unit="s"),
            )
            return df.dropna(subset=["Close"])
        except Exception as exc:  # noqa: BLE001
            log.warning("yahoo_direct history %s gagal: %s", ticker, exc)
            return pd.DataFrame()

    def last_price(self, ticker: str) -> float | None:
        try:
            data = self._fetch(ticker, "1d", "1m")
            meta = data["chart"]["result"][0]["meta"]
            price = meta.get("regularMarketPrice")
            return float(price) if price is not None else None
        except Exception as exc:  # noqa: BLE001
            log.debug("yahoo_direct last_price %s gagal: %s", ticker, exc)
            return None


class FMPProvider:
    """Financial Modeling Prep — gratis dengan API key (FMP_API_KEY).

    Mendukung simbol IDX dengan sufiks .JK. Batas free tier ~250 request/hari,
    cukup untuk watchlist kecil beberapa kali sehari.
    """

    BASE = "https://financialmodelingprep.com/api/v3"

    def history(self, ticker: str, period: str = "3mo", interval: str = "1d"):
        import pandas as pd

        if not settings.fmp_api_key:
            log.warning("FMP_API_KEY kosong — provider fmp tidak bisa dipakai.")
            return pd.DataFrame()
        n = {"5d": 5, "1mo": 22, "3mo": 66, "6mo": 132, "1y": 252}.get(period, 66)
        url = f"{self.BASE}/historical-price-full/{to_yahoo(ticker)}"
        try:
            data = _http_get_json(url, {"timeseries": n, "apikey": settings.fmp_api_key})
            rows = list(reversed(data.get("historical", [])))  # jadikan urut lama→baru
            if not rows:
                return pd.DataFrame()
            df = pd.DataFrame(rows)
            df.index = pd.to_datetime(df["date"])
            return df.rename(columns={
                "open": "Open", "high": "High", "low": "Low",
                "close": "Close", "volume": "Volume",
            })[["Open", "High", "Low", "Close", "Volume"]]
        except Exception as exc:  # noqa: BLE001
            log.warning("fmp history %s gagal: %s", ticker, exc)
            return pd.DataFrame()

    def last_price(self, ticker: str) -> float | None:
        if not settings.fmp_api_key:
            return None
        url = f"{self.BASE}/quote-short/{to_yahoo(ticker)}"
        try:
            data = _http_get_json(url, {"apikey": settings.fmp_api_key})
            return float(data[0]["price"]) if data else None
        except Exception as exc:  # noqa: BLE001
            log.debug("fmp last_price %s gagal: %s", ticker, exc)
            return None


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

    @staticmethod
    def _session():
        """Sesi curl_cffi (impersonate browser) bila tersedia — bantu hindari 429."""
        try:
            from curl_cffi import requests as creq

            return creq.Session(impersonate="chrome")
        except ImportError:
            return None

    def _ticker(self, ticker: str):
        import yfinance as yf

        sess = self._session()
        try:
            return yf.Ticker(to_yahoo(ticker), session=sess) if sess else yf.Ticker(to_yahoo(ticker))
        except TypeError:
            # Versi yfinance yang tidak menerima parameter session.
            return yf.Ticker(to_yahoo(ticker))

    def history(self, ticker: str, period: str = "3mo", interval: str = "1d"):
        import pandas as pd

        def _fetch():
            return self._ticker(ticker).history(period=period, interval=interval)

        df = self._retry(_fetch, "history", ticker)
        return df if df is not None else pd.DataFrame()

    def last_price(self, ticker: str) -> float | None:
        def _fetch():
            fi = self._ticker(ticker).fast_info
            price = fi.get("last_price") if hasattr(fi, "get") else fi["lastPrice"]
            return float(price) if price else None

        return self._retry(_fetch, "last_price", ticker)


class TwelveDataProvider:
    """Twelve Data — gratis dengan API key (TWELVEDATA_KEY).

    Free tier: 800 request/hari, 8/menit. Mendukung bursa IDX (exchange=IDX),
    dan umumnya dapat diakses dari IP VPS (tidak seperti Yahoo). REKOMENDASI
    utama bila sumber tanpa-key diblokir.
    """

    BASE = "https://api.twelvedata.com"
    _INTERVAL = {"1d": "1day", "1wk": "1week", "15m": "15min", "5m": "5min", "1m": "1min"}

    def _code(self, ticker: str) -> str:
        return ticker.upper().replace(".JK", "")

    def history(self, ticker: str, period: str = "3mo", interval: str = "1d"):
        import pandas as pd

        if not settings.twelvedata_key:
            log.warning("TWELVEDATA_KEY kosong — provider twelvedata tidak bisa dipakai.")
            return pd.DataFrame()
        n = {"5d": 5, "1mo": 25, "3mo": 70, "6mo": 130, "1y": 260}.get(period, 70)
        params = {
            "symbol": self._code(ticker), "exchange": "IDX",
            "interval": self._INTERVAL.get(interval, "1day"),
            "outputsize": n, "order": "ASC", "apikey": settings.twelvedata_key,
        }
        try:
            j = _http_get_json(f"{self.BASE}/time_series", params)
            if j.get("status") != "ok" or not j.get("values"):
                log.warning("twelvedata %s: %s", ticker, j.get("message", j.get("status")))
                return pd.DataFrame()
            df = pd.DataFrame(j["values"])
            df.index = pd.to_datetime(df["datetime"])
            for col in ("open", "high", "low", "close", "volume"):
                if col in df.columns:
                    df[col] = pd.to_numeric(df[col], errors="coerce")
            return df.rename(columns={
                "open": "Open", "high": "High", "low": "Low",
                "close": "Close", "volume": "Volume",
            })[["Open", "High", "Low", "Close", "Volume"]]
        except Exception as exc:  # noqa: BLE001
            log.warning("twelvedata history %s gagal: %s", ticker, exc)
            return pd.DataFrame()

    def last_price(self, ticker: str) -> float | None:
        if not settings.twelvedata_key:
            return None
        try:
            j = _http_get_json(f"{self.BASE}/price", {
                "symbol": self._code(ticker), "exchange": "IDX",
                "apikey": settings.twelvedata_key,
            })
            price = j.get("price")
            return float(price) if price else None
        except Exception as exc:  # noqa: BLE001
            log.debug("twelvedata last_price %s gagal: %s", ticker, exc)
            return None


class AlphaVantageProvider:
    """Alpha Vantage — gratis dengan API key (ALPHAVANTAGE_KEY).

    Kuota kecil (mis. 25 request/hari). Sufiks Jakarta: .JKT. Cadangan.
    """

    BASE = "https://www.alphavantage.co/query"

    def _symbol(self, ticker: str) -> str:
        return ticker.upper().replace(".JK", "") + ".JKT"

    def history(self, ticker: str, period: str = "3mo", interval: str = "1d"):
        import pandas as pd

        if not settings.alphavantage_key:
            log.warning("ALPHAVANTAGE_KEY kosong — provider alphavantage tidak bisa dipakai.")
            return pd.DataFrame()
        try:
            j = _http_get_json(self.BASE, {
                "function": "TIME_SERIES_DAILY", "symbol": self._symbol(ticker),
                "outputsize": "compact", "apikey": settings.alphavantage_key,
            })
            series = j.get("Time Series (Daily)")
            if not series:
                log.warning("alphavantage %s: %s", ticker, str(j)[:120])
                return pd.DataFrame()
            df = pd.DataFrame(series).T.rename(columns={
                "1. open": "Open", "2. high": "High", "3. low": "Low",
                "4. close": "Close", "5. volume": "Volume",
            })
            df.index = pd.to_datetime(df.index)
            df = df.sort_index()
            for c in ["Open", "High", "Low", "Close", "Volume"]:
                df[c] = pd.to_numeric(df[c], errors="coerce")
            return df[["Open", "High", "Low", "Close", "Volume"]]
        except Exception as exc:  # noqa: BLE001
            log.warning("alphavantage history %s gagal: %s", ticker, exc)
            return pd.DataFrame()

    def last_price(self, ticker: str) -> float | None:
        df = self.history(ticker, period="5d")
        if df is None or len(df) == 0:
            return None
        try:
            return float(df["Close"].iloc[-1])
        except Exception:  # noqa: BLE001
            return None


class StooqProvider:
    """Stooq.com — CSV harian gratis, tanpa API key, ramah IP data-center.

    Alternatif saat Yahoo memblokir IP VPS. Hanya data harian (EOD), jadi
    `last_price` memakai Close terakhir (bukan realtime). Format simbol IDX
    di Stooq bisa berbeda; sesuaikan `SUFFIX` bila diagnostik menunjukkan
    format lain (jalankan: python scripts/diag_data.py).
    """

    SUFFIX = ".jk"  # ubah ke ".id" atau "" bila diag_data.py menunjukkan begitu
    DL_URL = "https://stooq.com/q/d/l/"

    def _symbol(self, ticker: str) -> str:
        return ticker.upper().replace(".JK", "").lower() + self.SUFFIX

    def history(self, ticker: str, period: str = "3mo", interval: str = "1d"):
        import io

        import pandas as pd

        try:
            from curl_cffi import requests as creq
            r = creq.get(self.DL_URL, params={"s": self._symbol(ticker), "i": "d"},
                         impersonate="chrome", timeout=30)
            body = r.text
        except ImportError:
            import requests
            r = requests.get(self.DL_URL, params={"s": self._symbol(ticker), "i": "d"}, timeout=30)
            body = r.text

        if not body.lower().startswith("date"):
            log.warning("stooq history %s: respons tak terduga (%s)", ticker, body[:60])
            return pd.DataFrame()
        df = pd.read_csv(io.StringIO(body))
        df.index = pd.to_datetime(df["Date"])
        # Stooq: Date,Open,High,Low,Close,Volume (sudah kapital) — samakan bila perlu.
        df = df.rename(columns=str.capitalize)
        cols = [c for c in ["Open", "High", "Low", "Close", "Volume"] if c in df.columns]
        return df[cols]

    def last_price(self, ticker: str) -> float | None:
        df = self.history(ticker, period="5d")
        if df is None or len(df) == 0:
            return None
        try:
            return float(df["Close"].iloc[-1])
        except Exception:  # noqa: BLE001
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
    if name in ("yahoo_direct", "yahoo", "yahoodirect"):
        return YahooDirectProvider()
    if name == "yfinance":
        return YFinanceProvider()
    if name == "fmp":
        return FMPProvider()
    if name == "stooq":
        return StooqProvider()
    if name in ("twelvedata", "twelve_data", "td"):
        return TwelveDataProvider()
    if name in ("alphavantage", "alpha_vantage", "av"):
        return AlphaVantageProvider()
    # TODO: tambahkan GoAPIProvider / RTIProvider di sini untuk realtime.
    log.warning("Provider '%s' belum diimplementasikan — memakai NullProvider.", name)
    return NullProvider()
