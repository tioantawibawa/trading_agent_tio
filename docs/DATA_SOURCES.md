# Sumber Data

## Data harga (structured)

Pilih via `MARKET_DATA_PROVIDER` di `.env`.

| Provider | Key? | IDX free? | Catatan |
|----------|------|-----------|---------|
| **`yahoo_relay`** (default) | ❌ | ✅ | **Rekomendasi utama.** Data Yahoo penuh lewat **relay Cloudflare Worker milik Anda** — VPS memanggil Cloudflare (tak diblokir), Cloudflare memanggil Yahoo. Gratis, universe `.JK`. Setup: `scripts/cloudflare-worker.js`. |
| `fmp` | ✅ (gratis) | tergantung | Financial Modeling Prep. `FMP_API_KEY`. Coba dulu via `diag_data.py` (free tier kadang US-only). |
| `alphavantage` | ✅ (gratis) | tergantung | Kuota ~25 req/hari. Sufiks `.JKT`. |
| `twelvedata` | ✅ (gratis) | ❌ | Free tier **tidak** mencakup IDX (butuh plan Pro). |
| `yahoo_direct` / `yfinance` | ❌ | — | **Diblokir 429** dari IP data-center Tencent. |
| `stooq` | ❌ | ❌ | Tidak mencakup emiten IDX. |
| `goapi` / `rti` | ✅ (bayar) | — | Realtime. Perlu langganan. Implementasi menyusul. |

### Kenapa relay Cloudflare?

Diagnostik (`scripts/diag_data.py`) di VPS Tencent menunjukkan **semua sumber
gratis tanpa key buntu**: Yahoo membalas 429 (blokir IP data-center), Stooq
tak punya IDX, dan Twelve Data free tidak mencakup IDX. Yahoo sendiri gratis —
yang diblokir hanyalah IP-nya. Relay Cloudflare Workers (gratis, 100rb
req/hari) menembusnya tanpa mengorbankan kualitas/kelengkapan data.

**Setup ringkas:**
1. Buat akun Cloudflare gratis → Workers & Pages → Create Worker.
2. Tempel isi `scripts/cloudflare-worker.js` → Deploy.
3. (Disarankan) set variabel rahasia `RELAY_TOKEN` di Worker.
4. Di `.env`: `MARKET_DATA_PROVIDER=yahoo_relay`, `YAHOO_RELAY_URL=<url worker>`,
   `YAHOO_RELAY_TOKEN=<rahasia>`.
5. Uji: `YAHOO_RELAY_URL=<url> YAHOO_RELAY_TOKEN=<rahasia> python scripts/diag_data.py`

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
