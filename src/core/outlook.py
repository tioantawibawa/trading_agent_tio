"""Analisa prospek harga 7 hari ke depan (deterministik).

Untuk tiap saham menghitung: harga kini, tren (SMA5 vs SMA20), support/resistance,
ATR, proyeksi rentang harga ~7 hari bursa (skala volatilitas ATR·√7), target &
stop teknikal, dibulatkan ke fraksi harga BEI. Bila diberi avg_price (dari
portofolio), menambah floating P/L & saran aksi.

LLM (bila ada) hanya dipakai untuk 1 kalimat narasi — semua ANGKA deterministik.
Dipakai oleh Agent 6 / bot Telegram (perintah /target & /report) dan CLI.
"""
from __future__ import annotations

import math
from statistics import mean
from typing import Any

from src.config import settings
from src.core import idx_rules as idx
from src.core.indicators import atr, recent_support_resistance
from src.core.llm import complete
from src.core.logging_conf import get_logger
from src.core.market_data import get_provider

log = get_logger("outlook")

HORIZON_DAYS = 7  # hari bursa ke depan


def _rp(v: Any) -> str:
    if v is None:
        return "-"
    return "Rp" + f"{int(round(v)):,}".replace(",", ".")


def _trend(closes: list[float]) -> str:
    if len(closes) < 20:
        return "belum jelas"
    sma5, sma20 = mean(closes[-5:]), mean(closes[-20:])
    if sma5 > sma20 * 1.005 and closes[-1] >= sma20:
        return "naik"
    if sma5 < sma20 * 0.995 and closes[-1] <= sma20:
        return "turun"
    return "sideways"


def weekly_outlook(ticker: str, avg_price: float | None = None,
                   with_narrative: bool = False) -> dict[str, Any] | None:
    """Prospek 7 hari untuk satu saham. None bila data kurang."""
    provider = get_provider()
    df = provider.history(ticker, period="6mo", interval="1d")
    if df is None or len(df) < 20:
        log.warning("outlook %s: data harian kurang.", ticker)
        return None

    closes = [float(x) for x in df["Close"].tolist()]
    highs = [float(x) for x in df["High"].tolist()]
    lows = [float(x) for x in df["Low"].tolist()]

    current = provider.last_price(ticker) or closes[-1]
    a = atr(highs, lows, closes, settings.atr_period) or 0.0
    support, resistance = recent_support_resistance(highs, lows, settings.volume_lookback_days)
    trend = _trend(closes)

    band = a * math.sqrt(HORIZON_DAYS)  # ekspektasi pergerakan ~7 hari
    proj_low = idx.round_to_tick(max(current - band, 0), "down")
    proj_high = idx.round_to_tick(current + band, "up")

    # Target 7-hari: resisten terdekat di atas harga bila ada, jika tidak proyeksi atas.
    target = idx.round_to_tick(resistance if resistance > current else proj_high, "up")
    # Stop teknikal: support terdekat di bawah, atau batas persentase.
    stop_pct = current * (1 - settings.max_stoploss_pct / 100)
    stop = idx.round_to_tick(support if 0 < support < current else stop_pct, "up")

    upside_pct = (target - current) / current * 100 if current else 0.0

    out: dict[str, Any] = {
        "ticker": ticker.upper(),
        "current": current,
        "trend": trend,
        "atr": round(a, 2),
        "support": idx.round_to_tick(support, "down") if support else None,
        "resistance": idx.round_to_tick(resistance, "up") if resistance else None,
        "proj_low": proj_low,
        "proj_high": proj_high,
        "target": target,
        "stop": stop,
        "upside_pct": round(upside_pct, 2),
        "horizon_days": HORIZON_DAYS,
    }

    if avg_price:
        out["avg_price"] = avg_price
        out["floating_pct"] = round((current - avg_price) / avg_price * 100, 2) if avg_price else None

    out["action"] = _recommendation(out)

    if with_narrative:
        out["narrative"] = complete(
            f"Dalam 1 kalimat ringkas (bahasa Indonesia), beri konteks prospek "
            f"saham {out['ticker']}: harga kini {_rp(current)}, tren {trend}, "
            f"target 7 hari {_rp(target)}, support {_rp(out['support'])}. "
            f"Objektif, tanpa ajakan beli/jual.", max_tokens=120,
        )
    return out


def _recommendation(o: dict[str, Any]) -> str:
    current, target, stop, trend = o["current"], o["target"], o["stop"], o["trend"]
    avg = o.get("avg_price")
    if avg:
        chg = o.get("floating_pct") or 0.0
        if current >= target:
            return "Pertimbangkan Take Profit (harga mendekati/menembus target)"
        if chg <= -settings.max_stoploss_pct or current <= stop:
            return "Waspada Cut Loss (di bawah toleransi risiko)"
        if trend == "turun":
            return "Tahan/kurangi — tren melemah"
        return "Hold — biarkan berjalan ke target"
    # Bukan posisi: sudut pandang calon entry.
    if o.get("support") and current <= o["support"] * 1.02 and trend != "turun":
        return "Area akumulasi (dekat support)"
    if current >= target * 0.98:
        return "Dekat target — tunggu pullback"
    return "Pantau"


def format_outlook_html(o: dict[str, Any]) -> str:
    lines = [
        f"📈 <b>{o['ticker']}</b> — prospek {o['horizon_days']} hari",
        f"Harga kini: <b>{_rp(o['current'])}</b> · Tren: {o['trend']}",
        f"Support {_rp(o['support'])} · Resistance {_rp(o['resistance'])}",
        f"Proyeksi {o['horizon_days']}h: {_rp(o['proj_low'])} – {_rp(o['proj_high'])}",
        f"🎯 Target: <b>{_rp(o['target'])}</b> ({o['upside_pct']:+.1f}%) · 🛑 Stop: {_rp(o['stop'])}",
    ]
    if o.get("avg_price"):
        lines.append(f"Avg beli {_rp(o['avg_price'])} · Floating {o.get('floating_pct'):+.1f}%")
    lines.append(f"💡 {o['action']}")
    if o.get("narrative"):
        lines.append(f"<i>{o['narrative']}</i>")
    return "\n".join(lines)


def target_report(ticker: str, avg_price: float | None = None) -> str:
    o = weekly_outlook(ticker, avg_price=avg_price, with_narrative=True)
    if not o:
        return f"Maaf, data untuk {ticker.upper()} tidak cukup untuk analisa."
    return format_outlook_html(o)


def portfolio_report() -> str:
    """Laporan prospek 7 hari untuk seluruh posisi portofolio tersimpan."""
    from src.core import database as dbm

    positions = dbm.get_portfolio()
    if not positions:
        return ("Portofolio kosong. Kirim screenshot portofolio ke bot untuk "
                "mengisinya, lalu jalankan /report lagi.")

    blocks = [f"🗂️ <b>Laporan Portofolio — prospek {HORIZON_DAYS} hari</b>\n"]
    total_pl = 0.0
    for pos in positions:
        o = weekly_outlook(pos["ticker"], avg_price=pos.get("avg_price"))
        if not o:
            blocks.append(f"• {pos['ticker']}: data tidak cukup.")
            continue
        lots = pos.get("lots") or 0
        if o.get("avg_price") and o.get("floating_pct") is not None:
            total_pl += lots * 100 * (o["current"] - o["avg_price"])
        blocks.append(format_outlook_html(o))
    if total_pl:
        blocks.append(f"\n<b>Total floating P/L estimasi: {_rp(total_pl)}</b>")
    blocks.append("\n⚠️ Alat bantu analisa, bukan nasihat keuangan.")
    return "\n\n".join(blocks)
