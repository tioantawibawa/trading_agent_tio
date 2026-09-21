# Arsitektur

## Prinsip

- **Schedule-driven + event-driven**, bukan loop agent mandiri. Orchestrator
  (`src/orchestrator.py`) memakai APScheduler untuk memicu agent pada jam tepat
  (WIB). Ini deterministik & hemat RAM/token.
- **Deterministik untuk angka.** Semua level harga (Entry/TP/SL, support,
  resistance, ATR, pivot, ARA/ARB, fraksi harga) dihitung dengan formula di
  `src/core/indicators.py` & `src/core/idx_rules.py`. LLM (`src/core/llm.py`)
  hanya untuk narasi/sentimen & vision — tidak pernah mengarang angka.
- **Separation of concerns.** Tiap agent punya kontrak input/output lewat DB
  (`src/core/database.py`) & file JSON, sehingga bisa diuji terpisah.
- **Adapter pluggable.** Sumber data pasar di balik `MarketDataProvider`
  (`src/core/market_data.py`) — ganti yfinance → GoAPI/RTI tanpa menyentuh agent.

## Aliran Data

```
Agent 1 ──(daily_data, sentiment)──► DB
                                       │
Agent 2 ──(baca daily_data+sentiment)─┤──► trade_plan(stage=screened)
                                       │
Agent 3 ──(baca trade_plan+daily_data)┤──► trade_plan(stage=planned)
                                       │
Agent 4 ──(baca trade_plan+sentiment)─┴──► Email
Agent 5 ──(baca trade_plan+portfolio)──────► Telegram alert
Agent 6 ──(screenshot)──► Vision LLM ──────► portfolio (DB) ► Telegram feedback
```

## Tabel DB (SQLite)

| Tabel | Isi |
|-------|-----|
| `watchlist` | ticker yang dipantau |
| `daily_data` | OHLCV + seri harga (JSON) per ticker/tanggal |
| `sentiment` | ringkasan sentimen & headline harian |
| `trade_plan` | shortlist (screened) → plan lengkap (planned) |
| `portfolio` | posisi hasil ekstraksi screenshot |
| `alerts` | log alert Telegram (untuk anti-spam) |

## Menambah sumber realtime

Implementasikan kelas dengan method `history()` & `last_price()` (lihat
`YFinanceProvider`), lalu daftarkan di `get_provider()`. Set
`MARKET_DATA_PROVIDER` di `.env`.

## Menambah agent baru

1. Buat `src/agents/agentN_xxx.py` dengan fungsi `run()`.
2. Daftarkan job-nya di `src/orchestrator.py`.
3. Tambahkan ke `src/cli.py` bila perlu dijalankan manual.
