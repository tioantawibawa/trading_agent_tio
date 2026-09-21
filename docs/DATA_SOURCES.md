# Sumber Data

## Data harga (structured)

Pilih via `MARKET_DATA_PROVIDER` di `.env`.

| Provider | Key? | Realtime | Catatan |
|----------|------|----------|---------|
| **`yahoo_direct`** (default, gratis) | ❌ | delay ~15 mnt | **Rekomendasi untuk VPS.** Akses endpoint chart Yahoo langsung memakai `curl_cffi` (impersonasi browser) → tahan blokir **HTTP 429** yang menimpa yfinance di IP data-center. Universe `.JK`. |
| `yfinance` | ❌ | delay ~15 mnt | Library yfinance. Sering kena 429 dari IP VPS. Kini juga memakai sesi `curl_cffi` bila terpasang. |
| `fmp` | ✅ (gratis) | ~EOD | Financial Modeling Prep. Daftar gratis → `FMP_API_KEY`. Batas ~250 req/hari. Mendukung sufiks `.JK`. |
| `goapi` | ✅ (bayar) | ✅ | GoAPI.id. Perlu `GOAPI_KEY`. Buat `GoAPIProvider` di `market_data.py`. |
| `rti` / websocket sekuritas | ✅ (bayar) | ✅ | Perlu langganan/izin. Hormati ToS. |

> **Kalau kena 429 terus:** ganti ke `MARKET_DATA_PROVIDER=yahoo_direct` dan
> pastikan `curl_cffi` terpasang (`pip install curl_cffi`). Ini biasanya
> menyelesaikan blokir karena permintaan menyamar sebagai browser asli.
> Jika masih diblokir (IP VPS masuk daftar hitam Yahoo), pakai `fmp`
> (gratis, butuh key) atau provider berbayar.

> **Konsekuensi delay:** dengan sumber gratis, Agent 5 mengalarm berdasarkan
> harga tertunda ~15 menit. Untuk sinyal intraday presisi, pakai provider
> realtime dan arahkan strategi sesuai (jangan scalping dengan data delay).

## Data tak terstruktur (news/sentimen)

`src/core/news.py` menarik RSS dari portal finansial (CNBC Indonesia, Kontan,
Bisnis.com — dapat diubah). Untuk sumber tanpa RSS:

- **Keterbukaan Informasi IDX** — perlu scraper khusus; hormati robots.txt.
- **Forum (mis. Stockbit Stream)** — hormati ToS; hindari scraping yang dilarang.

Sentimen agregat diringkas oleh LLM (opsional) di Agent 1. Tanpa LLM, sistem
memakai heuristik hitung-sebutan (`mentioned_tickers`).

## LLM (narasi & vision)

Set `LLM_PROVIDER` di `.env`:

| Provider | Paket | Catatan |
|----------|-------|---------|
| `anthropic` | `anthropic` | SDK resmi, format Messages. Isi `ANTHROPIC_API_KEY`. |
| `openrouter` | `openai` | Endpoint OpenAI-compatible (`https://openrouter.ai/api/v1`). Bisa akses banyak model (Claude, Gemini, dll.). Isi `OPENROUTER_API_KEY` dan set `LLM_MODEL` ke nama format OpenRouter, mis. `anthropic/claude-3.5-haiku`. Untuk Agent 6 (vision) pilih model yang mendukung gambar. |
| `none` | — | Lewati LLM; sistem pakai template & heuristik. |

> Catatan OpenRouter: nama model **wajib** berformat `vendor/model`
> (mis. `anthropic/claude-3.5-haiku`, `google/gemini-2.0-flash-001`), bukan ID
> Anthropic langsung. Field `ANTHROPIC_API_KEY` tidak dipakai saat provider
> `openrouter` — yang dipakai `OPENROUTER_API_KEY`.

## Kepatuhan

- Gunakan hanya data yang Anda berhak akses. Periksa ToS tiap sumber.
- Simpan API key di `.env` (`chmod 600`), jangan commit.
