"""Agent 1 — Data Harvester (structured + unstructured).

Jadwal: 07.30–08.45 WIB (pra-pembukaan) dan malam hari.
Tugas:
  - Ambil data terstruktur: OHLCV & penutupan kemarin untuk watchlist.
  - Ambil data tak terstruktur: headline berita dari RSS.
  - (Opsional) Ringkas sentimen pasar & katalis sektoral via LLM.
Output: tersimpan ke DB (daily_data + sentiment) dan file JSON di data/reports.
"""
from __future__ import annotations

import json
from datetime import date
from typing import Any

from src.config import settings
from src.core import database as dbm
from src.core import news as newsm
from src.core.llm import complete
from src.core.logging_conf import get_logger
from src.core.market_data import get_provider

log = get_logger("agent1")


def _collect_structured(tickers: list[str]) -> dict[str, dict[str, Any]]:
    import time

    provider = get_provider()
    out: dict[str, dict[str, Any]] = {}
    for i, tk in enumerate(tickers):
        if i:
            time.sleep(1.0)  # jeda antar-ticker untuk meredam rate-limit Yahoo
        try:
            df = provider.history(tk, period="3mo", interval="1d")
            if df is None or len(df) == 0:
                continue
            last = df.iloc[-1]
            payload = {
                "prev_close": float(last["Close"]),
                "prev_open": float(last["Open"]),
                "prev_high": float(last["High"]),
                "prev_low": float(last["Low"]),
                "prev_volume": float(last["Volume"]),
                # Simpan seri untuk dipakai Agent 2/3 (hemat panggilan ulang).
                "closes": [float(x) for x in df["Close"].tolist()],
                "highs": [float(x) for x in df["High"].tolist()],
                "lows": [float(x) for x in df["Low"].tolist()],
                "volumes": [float(x) for x in df["Volume"].tolist()],
            }
            dbm.save_daily_data(tk, payload)
            out[tk] = payload
        except Exception as exc:  # noqa: BLE001
            log.warning("Gagal ambil data terstruktur %s: %s", tk, exc)
    return out


def _summarize_sentiment(headlines: list[dict[str, Any]], mentions: dict[str, int]) -> str | None:
    if not headlines:
        return None
    titles = "\n".join(f"- {h['title']} ({h['source']})" for h in headlines[:40])
    prompt = (
        "Berikut headline berita pasar Indonesia hari ini:\n"
        f"{titles}\n\n"
        "Ringkas dalam 4-6 kalimat: sentimen umum pasar (positif/negatif/netral), "
        "katalis sektoral utama (mis. komoditas, suku bunga BI, perbankan), dan "
        "emiten/sektor yang paling ramai. Objektif, tanpa rekomendasi beli/jual."
    )
    return complete(prompt, max_tokens=600)


def run(dry_run: bool | None = None) -> dict[str, Any]:
    log.info("Agent 1 (Harvester) mulai.")
    dbm.init_db()

    # Gabungkan ticker dari .env ke DB (tambah yang belum ada) sehingga
    # menambah WATCHLIST di .env langsung terpakai. Untuk menghapus, gunakan
    # `./ta watchlist --remove ...` atau `--sync`.
    db_wl = set(dbm.get_watchlist())
    for tk in settings.watchlist_tickers:
        if tk not in db_wl:
            dbm.add_to_watchlist(tk, source="config")
    tickers = dbm.get_watchlist() or settings.watchlist_tickers
    if not tickers:
        log.warning("Watchlist kosong.")

    structured = _collect_structured(tickers)
    headlines = newsm.fetch_news()
    mentions = newsm.mentioned_tickers(headlines, tickers)
    summary = _summarize_sentiment(headlines, mentions)

    sentiment_payload = {
        "date": date.today().isoformat(),
        "headline_count": len(headlines),
        "top_mentions": mentions,
        "llm_summary": summary,
        "headlines": headlines[:50],
    }
    dbm.save_sentiment(sentiment_payload)

    report_path = settings.data_dir / "reports" / f"harvest_{date.today().isoformat()}.json"
    report_path.write_text(
        json.dumps(
            {"structured_tickers": list(structured.keys()), "sentiment": sentiment_payload},
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    log.info(
        "Agent 1 selesai: %d ticker, %d headline. Report: %s",
        len(structured), len(headlines), report_path,
    )
    return {"structured": structured, "sentiment": sentiment_payload}


if __name__ == "__main__":
    run()
