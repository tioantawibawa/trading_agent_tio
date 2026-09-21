"""Agent 4 — Executive Action Reporter (Email Dispatcher).

Jadwal: 09.15 WIB.
Menggabungkan sentimen (Agent 1) + trading plan kuantitatif (Agent 3) menjadi
satu email ringkas "Actionable Trade Plan": ringkasan IHSG pagi, tabel aksi
(Ticker | Rekomendasi | Entry | TP | SL | R:R), dan catatan katalis.
"""
from __future__ import annotations

from datetime import date
from typing import Any

from src.core import database as dbm
from src.core.logging_conf import get_logger
from src.core.notifier import send_email

log = get_logger("agent4")


def _rupiah(v: Any) -> str:
    if v is None:
        return "-"
    return f"Rp{int(v):,}".replace(",", ".")


def build_html(sentiment: dict[str, Any], plans: list[dict[str, Any]]) -> str:
    today = date.today().strftime("%A, %d %B %Y")
    summary = (sentiment or {}).get("llm_summary") or "Ringkasan sentimen belum tersedia."

    rows = ""
    for p in plans:
        rows += f"""
        <tr>
          <td style="padding:8px;border:1px solid #ddd;font-weight:bold">{p['ticker']}</td>
          <td style="padding:8px;border:1px solid #ddd">{p.get('recommendation','-')}</td>
          <td style="padding:8px;border:1px solid #ddd">{_rupiah(p.get('entry_low'))} – {_rupiah(p.get('entry_high'))}</td>
          <td style="padding:8px;border:1px solid #ddd;color:#137333">{_rupiah(p.get('take_profit'))}</td>
          <td style="padding:8px;border:1px solid #ddd;color:#b00020">{_rupiah(p.get('stop_loss'))}</td>
          <td style="padding:8px;border:1px solid #ddd;text-align:center">1:{p.get('rrr','-')}</td>
        </tr>
        <tr><td colspan="6" style="padding:6px 8px;border:1px solid #ddd;font-size:12px;color:#555">
          {p.get('narrative') or '; '.join(p.get('reasons') or [])}</td></tr>"""

    if not rows:
        rows = '<tr><td colspan="6" style="padding:12px;border:1px solid #ddd">Tidak ada kandidat yang lolos kriteria hari ini.</td></tr>'

    return f"""\
<html><body style="font-family:Arial,Helvetica,sans-serif;color:#222;max-width:720px;margin:auto">
  <h2 style="color:#0657C3">📈 Trading Plan Harian — {today}</h2>
  <h3>Ringkasan Sentimen IHSG Pagi</h3>
  <p style="line-height:1.5">{summary}</p>
  <h3>Action Plan</h3>
  <table style="border-collapse:collapse;width:100%;font-size:14px">
    <thead><tr style="background:#0657C3;color:#fff">
      <th style="padding:8px;border:1px solid #ddd">Ticker</th>
      <th style="padding:8px;border:1px solid #ddd">Rekomendasi</th>
      <th style="padding:8px;border:1px solid #ddd">Entry Range</th>
      <th style="padding:8px;border:1px solid #ddd">Target (TP)</th>
      <th style="padding:8px;border:1px solid #ddd">Stop Loss</th>
      <th style="padding:8px;border:1px solid #ddd">R:R</th>
    </tr></thead>
    <tbody>{rows}</tbody>
  </table>
  <p style="font-size:12px;color:#888;margin-top:24px">
    ⚠️ Alat bantu analisa, bukan nasihat keuangan. Angka Entry/TP/SL dihitung
    deterministik (ATR, support/resistance, fraksi harga BEI) dan dibatasi ARA/ARB.
    Keputusan akhir tetap di tangan Anda.
  </p>
</body></html>"""


def run(dry_run: bool | None = None) -> bool:
    log.info("Agent 4 (Reporter) mulai.")
    dbm.init_db()
    sentiment = dbm.get_sentiment() or {}
    plans = [p for p in dbm.get_active_plans() if p.get("stage") == "planned"]
    html = build_html(sentiment, plans)
    subject = f"[Trading Plan] {date.today().isoformat()} — {len(plans)} kandidat"
    ok = send_email(subject, html)
    log.info("Agent 4 selesai (email terkirim=%s, %d plan).", ok, len(plans))
    return ok


if __name__ == "__main__":
    run()
