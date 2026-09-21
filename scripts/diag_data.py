#!/usr/bin/env python3
"""Diagnostik sumber data pasar — jalankan DI VPS untuk tahu mana yang tembus.

Karena tiap penyedia bisa berbeda perlakuan terhadap IP VPS Anda (mis. Yahoo
memblokir IP data-center Tencent), skrip ini menguji beberapa sumber GRATIS
langsung dari VPS dan melaporkan mana yang mengembalikan data IDX.

Pakai (gabungkan key yang Anda punya — signup gratis, instan):
    python scripts/diag_data.py
    TWELVEDATA_KEY=xxx python scripts/diag_data.py
    FMP_API_KEY=xxx ALPHAVANTAGE_KEY=yyy TWELVEDATA_KEY=zzz python scripts/diag_data.py

Dapatkan key gratis:
    Twelve Data   -> https://twelvedata.com/pricing  (Basic/Free, 800 req/hari)
    Alpha Vantage -> https://www.alphavantage.co/support/#api-key
    FMP           -> https://site.financialmodelingprep.com/developer/docs

Tidak butuh paket proyek; hanya 'requests' (dan 'curl_cffi' bila ada).
"""
from __future__ import annotations

import os
import sys

TICKER = "BBCA"


def _get(url, params=None, as_json=True, timeout=25):
    """GET pakai curl_cffi (impersonate) bila ada, else requests."""
    try:
        from curl_cffi import requests as creq
        r = creq.get(url, params=params, impersonate="chrome", timeout=timeout)
        engine = "curl_cffi"
    except ImportError:
        import requests
        ua = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
              "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"}
        r = requests.get(url, params=params, headers=ua, timeout=timeout)
        engine = "requests"
    return r, engine


def test(name, fn):
    try:
        ok, detail = fn()
        mark = "✅ TEMBUS" if ok else "❌ gagal "
        print(f"{mark} | {name:28} | {detail}")
    except Exception as exc:  # noqa: BLE001
        print(f"❌ error  | {name:28} | {type(exc).__name__}: {exc}")


def t_yahoo():
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{TICKER}.JK"
    r, eng = _get(url, {"range": "5d", "interval": "1d"})
    if r.status_code != 200:
        return False, f"HTTP {r.status_code} (engine={eng})"
    n = len(r.json()["chart"]["result"][0].get("timestamp") or [])
    return n > 0, f"HTTP 200, {n} bar (engine={eng})"


def t_stooq(suffix):
    url = "https://stooq.com/q/d/l/"
    r, eng = _get(url, {"s": f"{TICKER.lower()}{suffix}", "i": "d"}, as_json=False)
    body = r.text.strip()
    ok = r.status_code == 200 and body.lower().startswith("date") and "\n" in body
    head = body.splitlines()[1] if ok and len(body.splitlines()) > 1 else body[:60]
    return ok, f"HTTP {r.status_code}, sample: {head!r} (engine={eng})"


def t_fmp():
    key = os.getenv("FMP_API_KEY")
    if not key:
        return False, "lewati (set FMP_API_KEY untuk uji)"
    url = f"https://financialmodelingprep.com/api/v3/historical-price-full/{TICKER}.JK"
    r, eng = _get(url, {"timeseries": 5, "apikey": key})
    if r.status_code != 200:
        return False, f"HTTP {r.status_code}: {r.text[:80]}"
    hist = r.json().get("historical", []) if isinstance(r.json(), dict) else []
    return len(hist) > 0, f"HTTP 200, {len(hist)} bar (engine={eng})"


def t_alpha():
    key = os.getenv("ALPHAVANTAGE_KEY")
    if not key:
        return False, "lewati (set ALPHAVANTAGE_KEY untuk uji)"
    url = "https://www.alphavantage.co/query"
    # Alpha Vantage sufiks Jakarta: .JKT
    r, eng = _get(url, {"function": "TIME_SERIES_DAILY", "symbol": f"{TICKER}.JKT",
                        "outputsize": "compact", "apikey": key})
    j = r.json()
    series = j.get("Time Series (Daily)")
    if series:
        return True, f"HTTP 200, {len(series)} bar (engine={eng})"
    return False, f"tak ada data: {str(j)[:120]}"


def t_twelvedata():
    key = os.getenv("TWELVEDATA_KEY")
    if not key:
        return False, "lewati (set TWELVEDATA_KEY untuk uji)"
    url = "https://api.twelvedata.com/time_series"
    r, eng = _get(url, {"symbol": TICKER, "exchange": "IDX", "interval": "1day",
                        "outputsize": 5, "apikey": key})
    j = r.json()
    if j.get("status") == "ok" and j.get("values"):
        return True, f"HTTP 200, {len(j['values'])} bar (engine={eng})"
    return False, f"{j.get('status','?')}: {j.get('message', str(j)[:120])}"


def t_relay():
    base = os.getenv("YAHOO_RELAY_URL")
    if not base:
        return False, "lewati (set YAHOO_RELAY_URL untuk uji relay Cloudflare)"
    params = {"symbol": f"{TICKER}.JK", "range": "5d", "interval": "1d"}
    tok = os.getenv("YAHOO_RELAY_TOKEN")
    if tok:
        params["token"] = tok
    r, eng = _get(base.rstrip("/"), params)
    if r.status_code != 200:
        return False, f"HTTP {r.status_code}: {r.text[:80]}"
    n = len(r.json()["chart"]["result"][0].get("timestamp") or [])
    return n > 0, f"HTTP 200, {n} bar (engine={eng})"


def main():
    print(f"Menguji sumber data untuk {TICKER}.JK dari IP VPS ini...\n")
    test("Yahoo relay (Cloudflare)", t_relay)
    test("Yahoo chart (yahoo_direct)", t_yahoo)
    test("Stooq  suffix .jk", lambda: t_stooq(".jk"))
    test("Stooq  suffix .id", lambda: t_stooq(".id"))
    test("Stooq  tanpa suffix", lambda: t_stooq(""))
    test("Twelve Data (exchange=IDX)", t_twelvedata)
    test("FMP (financialmodelingprep)", t_fmp)
    test("Alpha Vantage", t_alpha)
    print("\nCatatan: yang '✅ TEMBUS' bisa dipakai. Set MARKET_DATA_PROVIDER di .env "
          "sesuai pemenang (mis. 'stooq' atau 'fmp'), lalu kabari hasilnya.")


if __name__ == "__main__":
    sys.exit(main())
