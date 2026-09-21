"""Entrypoint CLI.

Contoh:
  python -m src.cli serve                 # orchestrator penuh (scheduler + monitor)
  python -m src.cli bot                    # jalankan bot Telegram
  python -m src.cli run-agent 1            # jalankan satu agent sekali
  python -m src.cli run-agent 2 --dry-run
  python -m src.cli pipeline               # jalankan Agent 1→2→3→4 berurutan
  python -m src.cli init-db                # buat skema DB
"""
from __future__ import annotations

import argparse

from src.config import settings
from src.core import database as dbm
from src.core.logging_conf import get_logger

log = get_logger("cli")


def _run_agent(num: int) -> None:
    if num == 1:
        from src.agents import agent1_harvester as m; m.run()
    elif num == 2:
        from src.agents import agent2_analyst as m; m.run()
    elif num == 3:
        from src.agents import agent3_quant as m; m.run()
    elif num == 4:
        from src.agents import agent4_reporter as m; m.run()
    elif num == 5:
        import asyncio
        from src.agents.agent5_monitor import run_forever
        asyncio.run(run_forever())
    elif num == 6:
        log.info("Agent 6 bersifat on-demand via bot Telegram (kirim screenshot). "
                 "Jalankan: python -m src.cli bot")
    else:
        raise SystemExit(f"Agent tidak dikenal: {num}")


def _doctor() -> None:
    """Cek kesehatan semua komponen (data, LLM, Telegram, Email, DB, service)."""
    import shutil
    import subprocess

    OK, BAD, WARN = "✅", "❌", "⚠️ "
    print("\n=== Trading Agent TIO — Health Check ===\n")

    # 1. Database
    try:
        dbm.init_db()
        wl = dbm.get_watchlist()
        plans = dbm.get_active_plans()
        port = dbm.get_portfolio()
        print(f"{OK} Database: {len(wl)} watchlist, {len(plans)} plan aktif, {len(port)} posisi")
    except Exception as exc:  # noqa: BLE001
        print(f"{BAD} Database: {exc}")

    # 2. Sumber data pasar
    try:
        from src.core.market_data import get_provider
        price = get_provider().last_price("BBCA")
        if price:
            print(f"{OK} Data pasar ({settings.market_data_provider}): BBCA = Rp{int(price)}")
        else:
            print(f"{BAD} Data pasar ({settings.market_data_provider}): tidak ada harga "
                  f"(cek YAHOO_RELAY_URL / provider / jaringan)")
    except Exception as exc:  # noqa: BLE001
        print(f"{BAD} Data pasar: {exc}")

    # 3. LLM
    prov = settings.llm_provider.lower()
    if prov == "none":
        print(f"{WARN}LLM: dinonaktifkan (LLM_PROVIDER=none) — memakai template")
    else:
        key = settings.openrouter_api_key if prov == "openrouter" else settings.anthropic_api_key
        if not key:
            print(f"{BAD} LLM ({prov}): API key kosong")
        else:
            try:
                from src.core.llm import _resolve_model
                print(f"{OK} LLM ({prov}): teks={_resolve_model('text')} · "
                      f"vision={_resolve_model('vision')}")
            except Exception as exc:  # noqa: BLE001
                print(f"{WARN}LLM ({prov}): key ada, tapi resolve model gagal: {exc}")

    # 4. Telegram
    if not settings.telegram_bot_token:
        print(f"{BAD} Telegram: TELEGRAM_BOT_TOKEN kosong")
    else:
        try:
            import requests
            r = requests.get(
                f"https://api.telegram.org/bot{settings.telegram_bot_token}/getMe", timeout=15)
            j = r.json()
            if j.get("ok"):
                who = j["result"].get("username")
                n = len(settings.allowed_chat_ids)
                mark = OK if n else WARN
                print(f"{mark}Telegram: bot @{who} aktif, {n} chat ID diizinkan"
                      + ("" if n else " (isi TELEGRAM_ALLOWED_CHAT_IDS!)"))
            else:
                print(f"{BAD} Telegram: token ditolak ({j})")
        except Exception as exc:  # noqa: BLE001
            print(f"{BAD} Telegram: {exc}")

    # 5. Email
    if settings.smtp_user and settings.smtp_password and settings.email_to:
        print(f"{OK} Email: SMTP {settings.smtp_user} → {settings.email_to} (kredensial ada)")
    else:
        print(f"{WARN}Email: kredensial SMTP belum lengkap (Agent 4 tidak kirim email)")

    # 6. Service systemd (mesin Agent 1-5 & bot Agent 6)
    if shutil.which("systemctl"):
        for svc in ("trading-agent", "trading-bot"):
            try:
                out = subprocess.run(["systemctl", "is-active", svc],
                                     capture_output=True, text=True, timeout=10)
                state = out.stdout.strip() or out.stderr.strip()
                mark = OK if state == "active" else BAD
                print(f"{mark}Service {svc}: {state}")
            except Exception as exc:  # noqa: BLE001
                print(f"{WARN}Service {svc}: {exc}")
    else:
        print(f"{WARN}systemctl tidak tersedia — cek service manual")

    print("\nCatatan: 'trading-agent' menjalankan Agent 1-5 (scheduler + monitor),")
    print("'trading-bot' menjalankan Agent 6 & perintah Telegram. Dry-run flag "
          f"DRY_RUN={settings.dry_run}.\n")


def _telegram_chatid() -> None:
    """Ambil Chat ID dari pesan terbaru ke bot (untuk mengisi
    TELEGRAM_ALLOWED_CHAT_IDS). Kirim /start ke bot Anda lebih dulu."""
    import requests

    if not settings.telegram_bot_token:
        log.error("TELEGRAM_BOT_TOKEN belum diisi di .env")
        return
    try:
        r = requests.get(
            f"https://api.telegram.org/bot{settings.telegram_bot_token}/getUpdates",
            timeout=30,
        )
        data = r.json()
    except Exception as exc:  # noqa: BLE001
        log.error("Gagal menghubungi Telegram: %s", exc)
        return
    if not data.get("ok"):
        log.error("Telegram menolak: %s", data)
        return
    seen: set[int] = set()
    for upd in data.get("result", []):
        msg = upd.get("message") or upd.get("edited_message") or upd.get("channel_post") or {}
        chat = msg.get("chat") or {}
        cid = chat.get("id")
        if cid and cid not in seen:
            seen.add(cid)
            nama = " ".join(filter(None, [chat.get("first_name"), chat.get("last_name")]))
            log.info("Chat ID: %s | %s | @%s | tipe=%s",
                     cid, nama or "-", chat.get("username", "-"), chat.get("type"))
    if not seen:
        log.info("Belum ada pesan terbaca. Kirim /start ke bot Anda di Telegram, "
                 "lalu jalankan perintah ini lagi.")
    else:
        log.info("Salin Chat ID di atas ke TELEGRAM_ALLOWED_CHAT_IDS di .env.")


def _watchlist(args) -> None:  # noqa: ANN001
    """Tampilkan / ubah watchlist yang tersimpan di DB."""
    dbm.init_db()

    def _split(s: str) -> list[str]:
        return [t.strip().upper() for t in s.split(",") if t.strip()]

    if args.sync:
        dbm.reset_watchlist()
        for tk in settings.watchlist_tickers:
            dbm.add_to_watchlist(tk, source="config")
        log.info("Watchlist di-reset dari .env (%d ticker).", len(settings.watchlist_tickers))
    if getattr(args, "lq45", False) or getattr(args, "preset", None):
        from src.core.presets import get_preset
        name = "lq45" if getattr(args, "lq45", False) else args.preset
        tickers = get_preset(name)
        if not tickers:
            log.error("Preset '%s' tidak dikenal.", name)
        else:
            for tk in tickers:
                dbm.add_to_watchlist(tk, source=f"preset:{name}")
            log.info("Preset %s ditambahkan (%d ticker).", name, len(tickers))
    if args.add:
        for tk in _split(args.add):
            dbm.add_to_watchlist(tk, source="cli")
        log.info("Ditambahkan: %s", ", ".join(_split(args.add)))
    if args.remove:
        for tk in _split(args.remove):
            dbm.remove_from_watchlist(tk)
        log.info("Dihapus: %s", ", ".join(_split(args.remove)))

    current = dbm.get_watchlist()
    log.info("Watchlist saat ini (%d): %s", len(current), ", ".join(current) or "(kosong)")


def _pipeline() -> None:
    """Jalankan alur pagi lengkap sekali (untuk uji end-to-end)."""
    from src.agents import (
        agent1_harvester, agent2_analyst, agent3_quant, agent4_reporter,
    )
    agent1_harvester.run()
    agent2_analyst.run()
    agent3_quant.run()
    agent4_reporter.run()


def main() -> None:
    parser = argparse.ArgumentParser(prog="trading-agent-tio")
    # Flag bersama untuk semua subcommand.
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument(
        "--dry-run", action="store_true",
        help="Jangan kirim notifikasi/email sungguhan (hanya log)",
    )

    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("serve", parents=[common], help="Jalankan orchestrator (scheduler + monitor)")
    sub.add_parser("bot", parents=[common], help="Jalankan bot Telegram (Agent 5/6)")
    sub.add_parser("pipeline", parents=[common], help="Jalankan Agent 1→4 berurutan sekali")
    sub.add_parser("init-db", parents=[common], help="Inisialisasi skema database")
    sub.add_parser("alerts", parents=[common], help="Tampilkan riwayat alert terakhir")
    sub.add_parser("doctor", parents=[common], help="Cek kesehatan semua komponen/agent")
    sub.add_parser("status", parents=[common], help="Alias 'doctor'")
    sub.add_parser("llm-model", parents=[common], help="Tampilkan model LLM yang terpilih")
    sub.add_parser("telegram-chatid", parents=[common],
                   help="Tampilkan Chat ID dari pesan terbaru ke bot Telegram")

    tv = sub.add_parser("test-vision", parents=[common],
                        help="Uji baca gambar (Agent 6) dari file lokal")
    tv.add_argument("image", help="Path file gambar (png/jpg)")

    sub.add_parser("reconcile", parents=[common],
                   help="Rekonsiliasi manual: nonaktifkan semua trade plan hari ini")
    sub.add_parser("report", parents=[common],
                   help="Laporan prospek 7 hari untuk portofolio")
    sub.add_parser("review", parents=[common],
                   help="Review pergerakan portofolio hari ini (uji job 16.50)")
    tg = sub.add_parser("target", parents=[common],
                        help="Prospek 7 hari satu saham")
    tg.add_argument("ticker", help="Kode saham IDX, mis. BBCA")

    wl = sub.add_parser("watchlist", parents=[common], help="Kelola watchlist")
    wl.add_argument("--add", help="Tambah ticker (pisah koma), mis. GOTO,BRIS")
    wl.add_argument("--remove", help="Hapus ticker (pisah koma)")
    wl.add_argument("--sync", action="store_true",
                    help="Reset watchlist = WATCHLIST di .env")
    wl.add_argument("--lq45", action="store_true",
                    help="Tambahkan seluruh konstituen LQ45 ke watchlist")
    wl.add_argument("--preset", help="Tambahkan preset bernama (mis. lq45)")

    ra = sub.add_parser("run-agent", parents=[common], help="Jalankan satu agent")
    ra.add_argument("number", type=int, choices=range(1, 7))

    args = parser.parse_args()

    if getattr(args, "dry_run", False):
        settings.dry_run = True
        log.info("Mode DRY_RUN aktif.")

    if args.cmd == "serve":
        from src.orchestrator import main as serve_main
        serve_main()
    elif args.cmd == "bot":
        from src.telegram_bot import run_bot
        run_bot()
    elif args.cmd == "pipeline":
        _pipeline()
    elif args.cmd == "init-db":
        dbm.init_db()
        log.info("Skema DB dibuat di %s", settings.db_path)
    elif args.cmd == "llm-model":
        from src.core.llm import _resolve_model
        log.info("Provider: %s", settings.llm_provider)
        log.info("Model teks   : %s", _resolve_model("text") or "(tidak ada / template)")
        log.info("Model vision : %s", _resolve_model("vision") or "(tidak ada / template)")
    elif args.cmd == "alerts":
        rows = dbm.get_recent_alerts(25)
        if not rows:
            log.info("Belum ada alert tercatat.")
        for r in rows:
            log.info("%s | %-7s | %s | %s", r["created_at"][:19], r["kind"],
                     r["ticker"], (r["message"] or "")[:80])
    elif args.cmd in ("doctor", "status"):
        _doctor()
    elif args.cmd == "telegram-chatid":
        _telegram_chatid()
    elif args.cmd == "test-vision":
        import mimetypes
        from pathlib import Path
        from src.agents.agent6_portfolio import analyze_screenshot
        p = Path(args.image)
        if not p.exists():
            log.error("File tidak ditemukan: %s", p)
            return
        mt = mimetypes.guess_type(str(p))[0] or "image/png"
        res = analyze_screenshot(p.read_bytes(), media_type=mt)
        log.info("Ringkasan:\n%s", res["summary"])
    elif args.cmd == "reconcile":
        n = len(dbm.get_active_plans())
        dbm.deactivate_plans()
        log.info("Rekonsiliasi: %d trade plan dinonaktifkan.", n)
    elif args.cmd == "report":
        from src.core.outlook import portfolio_report
        import re
        print(re.sub(r"</?b>|</?i>", "", portfolio_report()))
    elif args.cmd == "review":
        from src.core.outlook import portfolio_daily_review
        import re
        print(re.sub(r"</?b>|</?i>", "", portfolio_daily_review()))
    elif args.cmd == "target":
        from src.core.outlook import target_report
        import re
        avg = next((p.get("avg_price") for p in dbm.get_portfolio()
                    if p["ticker"] == args.ticker.upper()), None)
        print(re.sub(r"</?b>|</?i>", "", target_report(args.ticker, avg_price=avg)))
    elif args.cmd == "watchlist":
        _watchlist(args)
    elif args.cmd == "run-agent":
        _run_agent(args.number)


if __name__ == "__main__":
    main()
