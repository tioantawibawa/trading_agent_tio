# Deploy di VPS

## 1. Persiapan

```bash
sudo adduser tio            # jalankan sebagai user non-root
sudo su - tio
git clone <repo-url> trading_agent_tio
cd trading_agent_tio
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
```

## 2. Konfigurasi & keamanan kredensial

```bash
cp .env.example .env
nano .env                    # isi API keys, token Telegram, SMTP, dst.
chmod 600 .env               # hanya pemilik yang bisa baca
```

- **Telegram:** buat bot via @BotFather, salin token ke `TELEGRAM_BOT_TOKEN`.
  Dapatkan Chat ID Anda (kirim pesan ke bot lalu cek
  `https://api.telegram.org/bot<TOKEN>/getUpdates`), isi ke
  `TELEGRAM_ALLOWED_CHAT_IDS`. **Hanya ID ini yang dilayani** — orang lain
  tidak bisa melihat portofolio atau memberi perintah.
- **Email (Gmail):** aktifkan 2FA, buat *App Password*, isi `SMTP_PASSWORD`.
- **LLM:** isi `ANTHROPIC_API_KEY` (atau set `LLM_PROVIDER=none` untuk mode
  tanpa LLM — sistem tetap jalan dengan template).

## 3. Uji sebelum produksi

```bash
python -m src.cli init-db
python -m src.cli run-agent 1                 # cek harvest data & berita
python -m src.cli pipeline --dry-run          # Agent 1→4 tanpa kirim email
pytest -q                                     # unit test formula
```

## 4. Jalankan sebagai service

```bash
# File .service sudah disetel untuk user 'ubuntu' & /home/ubuntu/trading_agent_tio.
# Bila username/lokasi berbeda, edit User= dan path di kedua file lebih dulu.
sudo cp scripts/trading-agent.service /etc/systemd/system/
sudo cp scripts/trading-bot.service   /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now trading-agent trading-bot
sudo systemctl status trading-agent trading-bot
journalctl -u trading-agent -f               # pantau log
```

Service membaca `.env` langsung dari `WorkingDirectory` (via pydantic), jadi
tidak memakai `EnvironmentFile` — ini menghindari salah-parsing komentar inline
oleh systemd. Pastikan `.env` berada di folder proyek dan `chmod 600`.

- `trading-agent` = orchestrator (Agent 1-5 terjadwal + monitor intraday).
- `trading-bot` = bot Telegram (perintah + screenshot Agent 6).

## 5. Hardening VPS (ringkas)

- Nonaktifkan login root SSH, gunakan kunci SSH, aktifkan `ufw`.
- Pastikan `.env` `chmod 600` dan tidak pernah ter-commit (sudah di `.gitignore`).
- Jalankan service sebagai user non-root (unit sudah menyetel `User=tio`).
- Backup file `data/trading_agent.db` secara berkala.

## Zona waktu

Semua jadwal memakai `TIMEZONE=Asia/Jakarta`. Pastikan paket `tzdata` tersedia
(`pip`/OS) agar `zoneinfo` menemukan zona.
