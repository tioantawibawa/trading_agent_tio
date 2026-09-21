"""Bot Telegram — antarmuka Agent 5 (alert) & Agent 6 (screenshot portofolio).

Keamanan: hanya Chat ID pada TELEGRAM_ALLOWED_CHAT_IDS yang boleh berinteraksi.
Semua pesan/foto dari ID lain diabaikan.

Perintah:
  /start, /help   — bantuan
  /plan           — tampilkan trading plan aktif hari ini
  /portfolio      — tampilkan ringkasan portofolio tersimpan
  (kirim foto)    — screenshot portofolio → diproses Agent 6
"""
from __future__ import annotations

from src.config import settings
from src.core import database as dbm
from src.core.logging_conf import get_logger

log = get_logger("telegram_bot")


def _authorized(update) -> bool:
    allowed = settings.allowed_chat_ids
    if not allowed:
        log.warning("TELEGRAM_ALLOWED_CHAT_IDS kosong — semua interaksi ditolak demi keamanan.")
        return False
    chat = update.effective_chat
    return bool(chat and chat.id in allowed)


async def cmd_start(update, context):  # noqa: ANN001
    if not _authorized(update):
        return
    await update.message.reply_text(
        "🤖 Trading Agent TIO aktif.\n\n"
        "Perintah:\n"
        "/plan — trading plan aktif hari ini\n"
        "/portfolio — ringkasan portofolio\n"
        "/report — prospek 7 hari untuk semua saham di portofolio\n"
        "/review — review pergerakan portofolio hari ini\n"
        "/target KODE — prospek 7 hari satu saham (mis. /target BBCA)\n"
        "/settarget KODE TP SL — set target profit & cut loss (alert otomatis)\n"
        "Kirim screenshot portofolio untuk dianalisa (target/stop dihitung otomatis)."
    )


async def cmd_plan(update, context):  # noqa: ANN001
    if not _authorized(update):
        return
    plans = [p for p in dbm.get_active_plans() if p.get("stage") == "planned"]
    if not plans:
        await update.message.reply_text("Belum ada trading plan aktif hari ini.")
        return
    lines = ["📋 <b>Trading Plan Aktif</b>"]
    for p in plans:
        lines.append(
            f"• <b>{p['ticker']}</b> ({p.get('recommendation','-')}) "
            f"Entry {p.get('entry_low')}–{p.get('entry_high')} | "
            f"TP {p.get('take_profit')} | SL {p.get('stop_loss')} | R:R 1:{p.get('rrr','-')}"
        )
    await update.message.reply_text("\n".join(lines), parse_mode="HTML")


async def cmd_portfolio(update, context):  # noqa: ANN001
    if not _authorized(update):
        return
    positions = dbm.get_portfolio()
    if not positions:
        await update.message.reply_text("Portofolio kosong. Kirim screenshot untuk mengisi.")
        return
    lines = ["📊 <b>Portofolio</b>"]
    for p in positions:
        lines.append(
            f"• {p['ticker']}: {p.get('lots')} lot @ Rp{p.get('avg_price')} "
            f"(now Rp{p.get('last_price')})"
        )
    lines.append("\nKetik /report untuk prospek 7 hari tiap saham.")
    await update.message.reply_text("\n".join(lines), parse_mode="HTML")


async def cmd_target(update, context):  # noqa: ANN001
    if not _authorized(update):
        return
    from src.core.outlook import target_report

    args = context.args if hasattr(context, "args") else []
    if not args:
        await update.message.reply_text("Format: /target KODE (mis. /target BBCA)")
        return
    ticker = args[0].upper()
    # Ambil avg_price dari portofolio bila saham ini dimiliki.
    avg = next((p.get("avg_price") for p in dbm.get_portfolio()
                if p["ticker"] == ticker), None)
    await update.message.reply_text(f"⏳ Menganalisa {ticker}…")
    text = target_report(ticker, avg_price=avg)
    await update.message.reply_text(text, parse_mode="HTML")


async def cmd_review(update, context):  # noqa: ANN001
    if not _authorized(update):
        return
    from src.core.outlook import portfolio_daily_review

    await update.message.reply_text("⏳ Menyusun review portofolio hari ini…")
    text = portfolio_daily_review()
    for chunk in [text[i:i + 3800] for i in range(0, len(text), 3800)]:
        await update.message.reply_text(chunk, parse_mode="HTML")


async def cmd_settarget(update, context):  # noqa: ANN001
    if not _authorized(update):
        return
    args = context.args if hasattr(context, "args") else []
    if len(args) < 3:
        await update.message.reply_text(
            "Format: /settarget KODE TARGET STOP\n"
            "Contoh: /settarget ANTM 3600 3100")
        return
    tk = args[0].upper()
    try:
        target = float(args[1].replace(".", "").replace(",", ""))
        stop = float(args[2].replace(".", "").replace(",", ""))
    except ValueError:
        await update.message.reply_text("TARGET dan STOP harus angka. Contoh: /settarget ANTM 3600 3100")
        return
    ok = dbm.set_position_targets(tk, target, stop)
    if ok:
        await update.message.reply_text(
            f"✅ {tk}: target Rp{int(target)} / stop Rp{int(stop)} tersimpan. "
            f"Notifikasi otomatis aktif saat harga menyentuhnya.")
    else:
        await update.message.reply_text(
            f"⚠️ {tk} tidak ada di portofolio. Kirim screenshot portofolio dulu.")


async def cmd_report(update, context):  # noqa: ANN001
    if not _authorized(update):
        return
    from src.core.outlook import portfolio_report

    await update.message.reply_text("⏳ Menyusun laporan portofolio 7 hari…")
    text = portfolio_report()
    # Telegram batasi ~4096 char; potong bila perlu.
    for chunk in [text[i:i + 3800] for i in range(0, len(text), 3800)]:
        await update.message.reply_text(chunk, parse_mode="HTML")


async def on_photo(update, context):  # noqa: ANN001
    if not _authorized(update):
        return
    from src.agents.agent6_portfolio import analyze_screenshot

    await update.message.reply_text("⏳ Menganalisa screenshot portofolio…")
    photo = update.message.photo[-1]  # resolusi tertinggi
    tg_file = await context.bot.get_file(photo.file_id)
    buf = await tg_file.download_as_bytearray()
    result = analyze_screenshot(bytes(buf), media_type="image/jpeg")
    await update.message.reply_text(result["summary"], parse_mode="HTML")


def build_application():
    """Bangun objek Application python-telegram-bot."""
    from telegram.ext import (
        Application,
        CommandHandler,
        MessageHandler,
        filters,
    )

    if not settings.telegram_bot_token:
        raise RuntimeError("TELEGRAM_BOT_TOKEN belum diisi di .env")

    app = Application.builder().token(settings.telegram_bot_token).build()
    app.add_handler(CommandHandler(["start", "help"], cmd_start))
    app.add_handler(CommandHandler("plan", cmd_plan))
    app.add_handler(CommandHandler("portfolio", cmd_portfolio))
    app.add_handler(CommandHandler("report", cmd_report))
    app.add_handler(CommandHandler("review", cmd_review))
    app.add_handler(CommandHandler("target", cmd_target))
    app.add_handler(CommandHandler("settarget", cmd_settarget))
    app.add_handler(MessageHandler(filters.PHOTO, on_photo))
    return app


def run_bot() -> None:
    dbm.init_db()
    app = build_application()
    log.info("Bot Telegram mulai (polling).")
    app.run_polling()


if __name__ == "__main__":
    run_bot()
