"""Pengiriman notifikasi: Telegram (async) & Email (SMTP).

Menghormati flag DRY_RUN — bila aktif, pesan hanya di-log, tidak dikirim.
"""
from __future__ import annotations

import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from src.config import settings
from src.core.logging_conf import get_logger

log = get_logger(__name__)


async def send_telegram(text: str, chat_id: int | None = None, parse_mode: str = "HTML") -> bool:
    """Kirim pesan Telegram ke chat_id (default: chat pertama yang diizinkan)."""
    if settings.dry_run:
        log.info("[DRY_RUN] Telegram -> %s\n%s", chat_id, text)
        return True
    if not settings.telegram_bot_token:
        log.warning("TELEGRAM_BOT_TOKEN kosong — pesan tidak dikirim.")
        return False
    target = chat_id or (settings.allowed_chat_ids[0] if settings.allowed_chat_ids else None)
    if target is None:
        log.warning("Tidak ada TELEGRAM_ALLOWED_CHAT_IDS — pesan tidak dikirim.")
        return False
    try:
        from telegram import Bot

        bot = Bot(token=settings.telegram_bot_token)
        await bot.send_message(chat_id=target, text=text, parse_mode=parse_mode)
        return True
    except Exception as exc:  # noqa: BLE001
        log.error("Gagal kirim Telegram: %s", exc)
        return False


def send_email(subject: str, html_body: str, to: str | None = None) -> bool:
    """Kirim email HTML via SMTP."""
    recipient = to or settings.email_to
    if settings.dry_run:
        log.info("[DRY_RUN] Email -> %s | %s\n%s", recipient, subject, html_body)
        return True
    if not (settings.smtp_user and settings.smtp_password and recipient):
        log.warning("Kredensial SMTP / penerima tidak lengkap — email tidak dikirim.")
        return False
    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = settings.email_from or settings.smtp_user
        msg["To"] = recipient
        msg.attach(MIMEText(html_body, "html", "utf-8"))
        with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=30) as srv:
            srv.starttls()
            srv.login(settings.smtp_user, settings.smtp_password)
            srv.send_message(msg)
        log.info("Email terkirim ke %s", recipient)
        return True
    except Exception as exc:  # noqa: BLE001
        log.error("Gagal kirim email: %s", exc)
        return False
