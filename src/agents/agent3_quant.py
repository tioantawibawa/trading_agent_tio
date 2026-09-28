"""Agent 3 — Quantitative Modeling & Execution Planner.

Input: shortlist dari Agent 2.
Untuk tiap saham menghitung (DETERMINISTIK, tanpa LLM):
  - Support/Resistance (lookback) & pivot intraday.
  - ATR untuk toleransi noise / lebar stop.
  - Entry area (rentang, dibulatkan ke fraksi harga BEI).
  - Take Profit (resisten terdekat) dgn RRR >= MIN_RRR.
  - Stop Loss (breakdown support / batas -MAX_STOPLOSS_PCT).
  - Rasio Risk-to-Reward.
Angka dibatasi tidak melebihi ARA/ARB harian.
Output: matriks trading plan terstruktur per saham (disimpan ke DB).
"""
from __future__ import annotations

from typing import Any

from src.config import settings
from src.core import database as dbm
from src.core import idx_rules as idx
from src.core.indicators import (
    atr,
    pivot_points,
    recent_support_resistance,
    rsi,
    trend_label,
)
from src.core.logging_conf import get_logger

log = get_logger("agent3")


def _confidence(trend: str, rsi_val: float | None, rrr: float | None) -> str:
    score = 0
    if trend == "naik":
        score += 1
    if rrr is not None and rrr >= 2.0:
        score += 1
    if rsi_val is not None and 45 <= rsi_val <= 70:
        score += 1
    return "Tinggi" if score >= 3 else "Sedang" if score == 2 else "Rendah"


def build_plan(ticker: str, daily: dict[str, Any]) -> dict[str, Any] | None:
    """Susun trading plan presisi.

    Filter kualitas (menghindari "pisau jatuh" & sinyal lemah):
      - Lewati bila tren TURUN (SMA5<SMA20 & harga<SMA20).
      - Entry di LEVEL bermakna: breakout di atas resistance, atau pullback ke
        support — bukan sekadar harga saat ini.
      - Stop berbasis struktur (di bawah support/level, buffer ATR) agar tidak
        whipsaw; trade yang butuh risiko > MAX_STOPLOSS_PCT dilewati.
      - Target dari resistance / measured-move, wajib RRR >= MIN_RRR.
    """
    highs = daily.get("highs") or []
    lows = daily.get("lows") or []
    closes = daily.get("closes") or []
    if len(closes) < max(settings.atr_period, 20) + 1:
        log.debug("%s: data kurang.", ticker)
        return None

    last = daily.get("intraday_last") or closes[-1]
    prev_close = daily.get("prev_close") or closes[-2]

    a = atr(highs, lows, closes, settings.atr_period) or 0.0
    if a <= 0:
        return None
    support, resistance = recent_support_resistance(highs, lows, settings.volume_lookback_days)
    if not (support and resistance and resistance > support):
        log.debug("%s: support/resistance tidak valid.", ticker)
        return None

    trend = trend_label(closes)
    rsi_val = rsi(closes, 14)

    # --- Filter 1: hindari beli saat tren turun ---
    if settings.require_uptrend and trend == "turun":
        log.info("%s dilewati: tren TURUN (hindari pisau jatuh).", ticker)
        return None

    near_breakout = last >= resistance * 0.99

    # --- Tentukan zona entry di level bermakna ---
    if near_breakout:
        recommendation = "Buy on Breakout"
        entry_low = idx.round_to_tick(resistance, "up")
        entry_high = idx.round_to_tick(resistance + 0.3 * a, "up")
        # Stop tepat di bawah level breakout (resistance jadi support baru).
        stop_base = resistance - 1.2 * a
    else:
        recommendation = "Buy on Weakness"
        # RSI tinggi + beli lemahan = rawan; lewati.
        if rsi_val is not None and rsi_val >= settings.rsi_overbought:
            log.info("%s dilewati: RSI %.0f overbought untuk Buy on Weakness.", ticker, rsi_val)
            return None
        entry_low = idx.round_to_tick(support, "down")
        entry_high = idx.round_to_tick(support + 0.6 * a, "up")
        stop_base = support - 0.8 * a
        # Jangan mengejar bila harga sudah jauh di atas zona pullback.
        if last > entry_high + 0.7 * a:
            log.info("%s dilewati: harga jauh di atas zona beli (hindari mengejar).", ticker)
            return None

    entry_ref = (entry_low + entry_high) / 2 or last
    stop_loss = idx.round_to_tick(stop_base, "up")
    if stop_loss >= entry_ref:
        stop_loss = idx.round_to_tick(entry_ref - 1.2 * a, "up")

    risk = entry_ref - stop_loss
    if risk <= 0:
        return None
    risk_pct = risk / entry_ref * 100
    # --- Filter 2: risiko stop wajar tidak boleh melebihi toleransi ---
    if risk_pct > settings.max_stoploss_pct:
        log.info("%s dilewati: stop wajar butuh risiko %.1f%% > batas %.1f%% (terlalu volatil).",
                 ticker, risk_pct, settings.max_stoploss_pct)
        return None

    # --- Target: resistance / measured-move, jamin RRR minimal ---
    if near_breakout:
        measured = resistance + (resistance - support)  # measured move klasik
        tp_candidate = max(measured, entry_ref + settings.min_rrr * risk)
    else:
        tp_candidate = max(resistance, entry_ref + settings.min_rrr * risk)
    take_profit = idx.round_to_tick(tp_candidate, "up")

    # Batasi ke ARA/ARB harian.
    ara = idx.ara_price(prev_close)
    arb = idx.arb_price(prev_close)
    take_profit = min(take_profit, ara)
    stop_loss = max(stop_loss, arb)

    risk = entry_ref - stop_loss
    reward = take_profit - entry_ref
    rrr = round(reward / risk, 2) if risk > 0 else None

    piv = pivot_points(daily.get("prev_high", highs[-1]),
                       daily.get("prev_low", lows[-1]), prev_close)

    return {
        "stage": "planned",
        "ticker": ticker.upper(),
        "recommendation": recommendation,
        "trend": trend,
        "rsi": round(rsi_val, 1) if rsi_val is not None else None,
        "confidence": _confidence(trend, rsi_val, rrr),
        "last_price": round(last, 2),
        "entry_low": entry_low,
        "entry_high": entry_high,
        "take_profit": take_profit,
        "stop_loss": stop_loss,
        "rrr": rrr,
        "risk_pct": round(risk_pct, 2),
        "atr": round(a, 2),
        "support": idx.round_to_tick(support, "down"),
        "resistance": idx.round_to_tick(resistance, "up"),
        "pivot": {k: idx.round_to_tick(v, "nearest") for k, v in piv.items()},
        "ara": ara,
        "arb": arb,
        "max_stoploss_pct": settings.max_stoploss_pct,
    }


def run(dry_run: bool | None = None) -> list[dict[str, Any]]:
    log.info("Agent 3 (Quant Planner) mulai.")
    dbm.init_db()
    screened = dbm.get_active_plans()
    plans: list[dict[str, Any]] = []
    for item in screened:
        tk = item["ticker"]
        daily = dbm.get_daily_data(tk)
        if not daily:
            continue
        plan = build_plan(tk, daily)
        if not plan:
            continue
        # Bawa serta narasi & alasan dari Agent 2.
        plan["narrative"] = item.get("narrative")
        plan["reasons"] = item.get("reasons")
        # Terapkan filter RRR minimum.
        if plan["rrr"] is not None and plan["rrr"] < settings.min_rrr:
            log.info("%s dibuang: RRR %.2f < %.2f", tk, plan["rrr"], settings.min_rrr)
            continue
        dbm.save_trade_plan(tk, plan)
        plans.append(plan)

    log.info("Agent 3 menghasilkan %d trading plan.", len(plans))
    return plans


if __name__ == "__main__":
    import json

    print(json.dumps(run(), ensure_ascii=False, indent=2))
