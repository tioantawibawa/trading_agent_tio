# Sumber Data

## Data harga (structured)

| Provider | Realtime | Catatan |
|----------|----------|---------|
| **yfinance** (default) | ❌ delay ~15 mnt | Gratis. Ticker IDX pakai sufiks `.JK` (mis. `BBCA.JK`). Cocok untuk swing/breakout harian, **bukan** scalping. |
| GoAPI.id | ✅ | Berbayar. Perlu `GOAPI_KEY`. Buat `GoAPIProvider` di `market_data.py`. |
| RTI / websocket sekuritas | ✅ | Perlu langganan/izin. Hormati ToS. |

> **Konsekuensi delay:** dengan yfinance, Agent 5 mengalarm berdasarkan harga
> tertunda. Untuk sinyal intraday presisi, pindah ke provider realtime dan
> arahkan strategi sesuai (jangan scalping dengan data delay).

## Data tak terstruktur (news/sentimen)

`src/core/news.py` menarik RSS dari portal finansial (CNBC Indonesia, Kontan,
Bisnis.com — dapat diubah). Untuk sumber tanpa RSS:

- **Keterbukaan Informasi IDX** — perlu scraper khusus; hormati robots.txt.
- **Forum (mis. Stockbit Stream)** — hormati ToS; hindari scraping yang dilarang.

Sentimen agregat diringkas oleh LLM (opsional) di Agent 1. Tanpa LLM, sistem
memakai heuristik hitung-sebutan (`mentioned_tickers`).

## Kepatuhan

- Gunakan hanya data yang Anda berhak akses. Periksa ToS tiap sumber.
- Simpan API key di `.env` (`chmod 600`), jangan commit.
