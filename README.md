# Trading Agent TIO — Multi-Agent AI untuk Bursa Saham Indonesia (IDX/BEI)

Sistem **multi-agent** untuk membantu perencanaan trading harian di Bursa Efek
Indonesia, dirancang untuk berjalan ringan di sebuah VPS. Arsitektur bersifat
*schedule-driven* + *event-driven* menggunakan Python `asyncio` + `APScheduler`,
sehingga hemat RAM dan deterministik (tidak boros token seperti agent
berbasis loop mandiri).

> ⚠️ **Disclaimer.** Ini adalah alat bantu analisa, **bukan** nasihat keuangan.
> Semua keputusan transaksi tetap ada di tangan Anda. Data harga gratis
> (mis. Yahoo Finance) memiliki *delay* ~15 menit — arahkan strategi ke
> *swing/breakout* harian, bukan *scalping* cepat. Lihat
> [`docs/DATA_SOURCES.md`](docs/DATA_SOURCES.md).

## Enam Agent

| # | Agent | Peran | Jadwal |
|---|-------|-------|--------|
| 1 | **Data Harvester** (`agent1_harvester`) | Kumpulkan data terstruktur (harga, foreign flow) & tak terstruktur (berita, sentimen) | 07.30–08.45 WIB & malam |
| 2 | **Morning Analyst** (`agent2_analyst`) | Screening saham potensial dari snapshot 10 menit pertama | 09.10 WIB |
| 3 | **Quant Planner** (`agent3_quant`) | Hitung Entry / TP / SL / RRR (deterministik, bukan LLM) | 09.10 WIB |
| 4 | **Executive Reporter** (`agent4_reporter`) | Rangkum jadi *Actionable Trade Plan* & kirim email | 09.15 WIB |
| 5 | **Realtime Monitor** (`agent5_monitor`) | Pantau harga live → alert Telegram (BUY/TP/CUT LOSS) | Jam bursa |
| 6 | **Portfolio Vision** (`agent6_portfolio`) | Baca screenshot portofolio via Telegram (Vision LLM) | On-demand |

**Perintah Telegram:** `/plan` (rencana hari ini), `/portfolio` (ringkasan),
`/report` (prospek 7 hari semua saham portofolio), `/target KODE` (prospek 7
hari satu saham), atau kirim screenshot portofolio. Setara CLI: `./ta report`,
`./ta target BBCA`.

## Alur Harian (WIB)

```
07.30–08.45  Agent 1  → scrape berita/sentimen + data penutupan → DB
09.00        Bursa Sesi 1 buka
09.10        Agent 2  → screening volume spike / momentum
             Agent 3  → hitung Entry/TP/SL/RRR untuk kandidat
09.15        Agent 4  → email Trading Plan harian
             Agent 5  → daftarkan saham ke Live Monitor
09.15–15.50  Agent 5  → polling harga → alert Telegram
             Agent 6  → siaga terima screenshot portofolio
16.00        Rekonsiliasi harian + reset watchlist
```

## Prinsip Desain

1. **Deterministik untuk angka.** Entry/TP/SL dihitung dengan formula
   (ATR, support/resistance, fraksi harga BEI) — LLM hanya merangkai narasi.
2. **Separation of concerns.** Tiap agent punya input/output jelas lewat DB &
   file JSON, bisa dijalankan/di-debug terpisah.
3. **Adapter data pluggable.** Sumber data (yfinance, GoAPI, RTI, dsb.) di
   balik interface tunggal — ganti tanpa mengubah agent.
4. **Aman.** Telegram bot dibatasi ke Chat ID Anda; semua kredensial di `.env`
   (`chmod 600`), tak pernah masuk ke git.

## Mulai Cepat

```bash
git clone <repo> && cd trading_agent_tio
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env        # isi kredensial Anda, lalu: chmod 600 .env

# Jalankan satu agent (dry-run, tanpa kirim notifikasi):
python -m src.cli run-agent 1 --dry-run
python -m src.cli run-agent 2

# Jalankan orchestrator (scheduler penuh):
python -m src.cli serve
```

Lihat [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) untuk detail desain, dan
[`docs/DEPLOY_VPS.md`](docs/DEPLOY_VPS.md) untuk setup systemd di VPS.

## Struktur

```
src/
  config.py            Pengaturan dari .env (pydantic-settings)
  cli.py               Entrypoint CLI (serve / run-agent / bot)
  orchestrator.py      Penjadwalan APScheduler
  telegram_bot.py      Bot Telegram (Agent 5 & 6 handler)
  core/
    database.py        Layer SQLite (watchlist, harga, plan, portofolio)
    idx_rules.py       Fraksi harga, ARA/ARB, jam bursa
    llm.py             Wrapper LLM pluggable (Anthropic default)
    notifier.py        Kirim Telegram & Email
    news.py            Fetch/parse RSS berita finansial
    market_data.py     Adapter data pasar (yfinance default)
  agents/
    agent1_harvester.py … agent6_portfolio.py
tests/                 Unit test formula deterministik
scripts/               systemd unit + helper deploy
```
