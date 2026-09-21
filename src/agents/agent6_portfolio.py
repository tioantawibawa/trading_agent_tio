"""Agent 6 — Portfolio Vision & Balance Tracker (multimodal).

On-demand: dipicu saat Anda mengirim screenshot aplikasi sekuritas ke bot
Telegram. Gambar diproses Vision LLM untuk mengekstrak posisi (emiten, lot,
avg price, harga kini, floating P/L, saldo kas), disimpan ke DB, lalu
memberi feedback ringkas alokasi risiko.

Modul ini menyediakan fungsi murni `analyze_screenshot(bytes)`; integrasi
Telegram ada di src/telegram_bot.py.
"""
from __future__ import annotations

import json
import re
from typing import Any

from src.core import database as dbm
from src.core.llm import read_image
from src.core.logging_conf import get_logger

log = get_logger("agent6")

_EXTRACT_PROMPT = """\
Anda membaca screenshot aplikasi sekuritas Indonesia (mis. Stockbit, Mirae,
IPOT, Mandiri Sekuritas). Ekstrak data portofolio menjadi JSON VALID dengan
skema berikut, tanpa teks lain:

{
  "cash_balance": <number|null>,
  "positions": [
    {"ticker": "<KODE>", "lots": <int|null>, "avg_price": <number|null>,
     "last_price": <number|null>, "floating_pl_rp": <number|null>,
     "floating_pl_pct": <number|null>}
  ]
}

Aturan: gunakan angka tanpa pemisah ribuan (1450 bukan 1.450). Jika sebuah
nilai tidak terbaca, isi null. Ticker adalah kode 4 huruf saham Indonesia.
"""


def _parse_json(text: str) -> dict[str, Any] | None:
    if not text:
        return None
    m = re.search(r"\{.*\}", text, re.DOTALL)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except json.JSONDecodeError:
        log.warning("Output vision bukan JSON valid.")
        return None


def _summarize(data: dict[str, Any]) -> str:
    positions = data.get("positions") or []
    if not positions:
        return "Tidak ada posisi terbaca dari screenshot."

    total_value = 0.0
    total_pl = 0.0
    for p in positions:
        lots = p.get("lots") or 0
        last = p.get("last_price") or 0
        total_value += lots * 100 * last  # 1 lot = 100 lembar
        total_pl += p.get("floating_pl_rp") or 0

    cash = data.get("cash_balance")
    lines = ["📊 <b>Ringkasan Portofolio</b>"]
    for p in positions:
        lines.append(
            f"• {p.get('ticker','?')}: {p.get('lots','?')} lot @ "
            f"Rp{p.get('avg_price','?')} | P/L {p.get('floating_pl_pct','?')}%"
        )
    if total_value:
        lines.append(f"\nEstimasi nilai posisi: Rp{int(total_value):,}".replace(",", "."))
    lines.append(f"Total floating P/L: Rp{int(total_pl):,}".replace(",", "."))
    if cash is not None:
        lines.append(f"Saldo kas: Rp{int(cash):,}".replace(",", "."))
    return "\n".join(lines)


def analyze_screenshot(image_bytes: bytes, media_type: str = "image/png") -> dict[str, Any]:
    """Proses screenshot → simpan posisi ke DB → kembalikan {data, summary}."""
    dbm.init_db()
    raw = read_image(image_bytes, _EXTRACT_PROMPT, media_type=media_type)
    if raw is None:
        log.warning("Agent 6: vision LLM mengembalikan None (model gagal/429/tak dukung gambar).")
        return {
            "data": None,
            "summary": "Maaf, model vision gagal membaca gambar (kemungkinan model "
            "gratis sibuk/rate-limit atau tak mendukung gambar). Coba kirim ulang, "
            "atau set LLM_VISION_MODEL ke model vision yang stabil di .env.",
        }
    log.info("Agent 6: respons vision (%d char): %.200s", len(raw), raw)
    data = _parse_json(raw)
    if not data:
        log.warning("Agent 6: respons vision bukan JSON valid: %.300s", raw)
        return {
            "data": None,
            "summary": "Maaf, hasil pembacaan tidak dalam format yang bisa diproses. "
            "Coba kirim ulang screenshot yang lebih jelas.",
        }

    # Perbarui DB portofolio, sekaligus hitung target profit & stop cut-loss
    # (deterministik, dari analisa 7-hari) agar Agent 5 bisa memantau otomatis.
    from src.core.outlook import weekly_outlook

    dbm.clear_portfolio()
    for p in data.get("positions", []):
        if not p.get("ticker"):
            continue
        target = stop = None
        try:
            o = weekly_outlook(p["ticker"], avg_price=p.get("avg_price"))
            if o:
                target, stop = o.get("target"), o.get("stop")
        except Exception as exc:  # noqa: BLE001
            log.debug("Gagal hitung target %s: %s", p["ticker"], exc)
        dbm.upsert_position(
            p["ticker"], p.get("lots"), p.get("avg_price"), p.get("last_price"),
            target_price=target, stop_price=stop, payload=p,
        )
    summary = _summarize(data)
    # Tambahkan target/stop yang terpasang (untuk alert otomatis Agent 5).
    tlines = ["\n🎯 <b>Target & Stop (auto, alert aktif)</b>"]
    for pos in dbm.get_portfolio():
        if pos.get("target_price") or pos.get("stop_price"):
            tlines.append(
                f"• {pos['ticker']}: TP Rp{int(pos['target_price']) if pos.get('target_price') else '-'} "
                f"/ SL Rp{int(pos['stop_price']) if pos.get('stop_price') else '-'}"
            )
    if len(tlines) > 1:
        summary += "\n" + "\n".join(tlines)
        summary += "\n\n<i>Anda akan menerima notifikasi otomatis saat harga menyentuh TP/SL. Ubah manual: /settarget KODE TP SL</i>"
    log.info("Agent 6: %d posisi diperbarui dari screenshot.", len(data.get("positions", [])))
    return {"data": data, "summary": summary}
