"""Agent 2 — Morning Market Analyst (screening ~09.10 WIB).

Mengambil snapshot 10 menit pertama sesi 1 dan menyaring saham dengan:
  - lonjakan volume tidak wajar (volume spike vs rata-rata 20 hari),
  - momentum pembukaan (gap-up yang tertahan / kenaikan awal),
digabung dengan sentimen & 'top mentions' dari Agent 1.

Output: shortlist maksimal MAX_CANDIDATES ticker, tersimpan agar Agent 3 pakai.
"""
from __future__ import annotations

from datetime import date
from typing import Any

from src.config import settings
from src.core import database as dbm
from src.core.indicators import volume_spike
from src.core.llm import complete
from src.core.logging_conf import get_logger
from src.core.market_data import get_provider

log = get_logger("agent2")


def _score_candidate(tk: str, daily: dict[str, Any], mentions: dict[str, int]) -> dict[str, Any] | None:
    """Beri skor kandidat berdasarkan volume spike, momentum, & sentimen."""
    volumes = daily.get("volumes") or []
    closes = daily.get("closes") or []
    if len(closes) < 2:
        return None

    spike = volume_spike(volumes, settings.volume_spike_multiplier, settings.volume_lookback_days)
    # Momentum: harga terkini (intraday bila ada) vs penutupan hari sebelumnya.
    last = daily.get("intraday_last") or closes[-1]
    ref = closes[-2]  # penutupan harian sebelum bar hari ini
    momentum = (last - ref) / ref if ref else 0.0
    mention_score = mentions.get(tk.upper(), 0)

    score = 0.0
    reasons: list[str] = []
    if spike["is_spike"]:
        score += 2.0
        reasons.append(f"volume spike {spike['ratio']:.1f}x rata-rata")
    if momentum > 0:
        score += min(momentum * 20, 2.0)
        reasons.append(f"momentum +{momentum*100:.1f}%")
    if mention_score:
        score += min(mention_score * 0.5, 1.5)
        reasons.append(f"ramai diberitakan ({mention_score}x)")

    if score <= 0:
        return None
    return {
        "ticker": tk.upper(),
        "score": round(score, 2),
        "volume_ratio": spike["ratio"],
        "momentum_pct": round(momentum * 100, 2),
        "mentions": mention_score,
        "last_price": last,
        "reasons": reasons,
    }


def _refresh_intraday(tickers: list[str]) -> None:
    """Simpan harga intraday terakhir sebagai field terpisah.

    PENTING: jangan menyisipkan bar 15-menit ke deret harian (closes/volumes),
    karena akan merusak deteksi volume-spike & momentum (volume 15m jauh lebih
    kecil dari rata-rata harian). Cukup simpan `intraday_last` untuk Agent 3.
    """
    provider = get_provider()
    for tk in tickers:
        try:
            df = provider.history(tk, period="5d", interval="15m")
            if df is None or len(df) == 0:
                continue
            daily = dbm.get_daily_data(tk) or {}
            daily["intraday_last"] = float(df["Close"].iloc[-1])
            dbm.save_daily_data(tk, daily)
        except Exception as exc:  # noqa: BLE001
            log.debug("Refresh intraday %s gagal: %s", tk, exc)


def run(dry_run: bool | None = None) -> list[dict[str, Any]]:
    log.info("Agent 2 (Morning Analyst) mulai.")
    dbm.init_db()
    tickers = dbm.get_watchlist() or settings.watchlist_tickers
    sentiment = dbm.get_sentiment() or {}
    mentions = sentiment.get("top_mentions", {})

    _refresh_intraday(tickers)

    scored: list[dict[str, Any]] = []
    for tk in tickers:
        daily = dbm.get_daily_data(tk)
        if not daily:
            continue
        cand = _score_candidate(tk, daily, mentions)
        if cand:
            log.info("  %s: skor %.2f (%s)", tk, cand["score"], ", ".join(cand["reasons"]))
            scored.append(cand)
        else:
            log.info("  %s: tidak lolos kriteria (tak ada spike/momentum/berita).", tk)

    scored.sort(key=lambda c: c["score"], reverse=True)
    shortlist = scored[: settings.max_candidates]

    # Narasi opsional dari LLM (hanya penjelasan, angka tetap deterministik).
    for c in shortlist:
        narrative = complete(
            "Jelaskan dalam 1 kalimat ringkas kenapa saham "
            f"{c['ticker']} menarik dipantau hari ini berdasarkan: "
            f"{', '.join(c['reasons'])}. Konteks sentimen pasar: "
            f"{sentiment.get('llm_summary', 'tidak ada')}.",
            max_tokens=120,
        )
        c["narrative"] = narrative or "; ".join(c["reasons"])

    # Simpan shortlist sebagai plan awal (Agent 3 melengkapi angka).
    for c in shortlist:
        dbm.save_trade_plan(c["ticker"], {"stage": "screened", **c})

    log.info("Agent 2 shortlist (%d): %s", len(shortlist), [c["ticker"] for c in shortlist])
    return shortlist


if __name__ == "__main__":
    import json

    print(json.dumps(run(), ensure_ascii=False, indent=2))
