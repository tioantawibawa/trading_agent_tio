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
from src.core.indicators import atr, pivot_points, recent_support_resistance
from src.core.logging_conf import get_logger

log = get_logger("agent3")


def build_plan(ticker: str, daily: dict[str, Any]) -> dict[str, Any] | None:
    highs = daily.get("highs") or []
    lows = daily.get("lows") or []
    closes = daily.get("closes") or []
    if len(closes) < settings.atr_period + 1:
        log.debug("%s: data kurang untuk ATR.", ticker)
        return None

    last = daily.get("intraday_last") or closes[-1]
    prev_close = daily.get("prev_close") or closes[-2]

    a = atr(highs, lows, closes, settings.atr_period) or 0.0
    support, resistance = recent_support_resistance(highs, lows, settings.volume_lookback_days)
    piv = pivot_points(daily.get("prev_high", highs[-1]),
                       daily.get("prev_low", lows[-1]),
                       prev_close)

    # Entry area: sekitar harga terakhir, lebar ~0.5 ATR, dibulatkan ke tick.
    entry_low = idx.round_to_tick(last - 0.25 * a, mode="down")
    entry_high = idx.round_to_tick(last + 0.25 * a, mode="up")
    entry_ref = (entry_low + entry_high) / 2 or last

    # Stop loss: max(breakdown support, batas persentase). Ambil yang lebih dekat
    # ke entry agar risiko modal terkontrol.
    sl_pct_limit = entry_ref * (1 - settings.max_stoploss_pct / 100)
    sl_support = support - 0.5 * a if support else sl_pct_limit
    stop_loss = idx.round_to_tick(max(sl_support, sl_pct_limit), mode="up")
    if stop_loss >= entry_ref:
        stop_loss = idx.round_to_tick(entry_ref - a, mode="up")

    risk = entry_ref - stop_loss
    if risk <= 0:
        log.debug("%s: risk non-positif, plan dilewati.", ticker)
        return None

    # Take profit: resisten terdekat, tapi pastikan RRR minimal terpenuhi.
    tp_by_rrr = entry_ref + settings.min_rrr * risk
    take_profit = idx.round_to_tick(max(resistance, tp_by_rrr), mode="up")
    reward = take_profit - entry_ref
    rrr = round(reward / risk, 2) if risk else None

    # Batasi ke ARA/ARB harian.
    ara = idx.ara_price(prev_close)
    arb = idx.arb_price(prev_close)
    take_profit = min(take_profit, ara)
    stop_loss = max(stop_loss, arb)

    recommendation = "Buy on Breakout" if last >= resistance * 0.99 else "Buy on Weakness"

    plan = {
        "stage": "planned",
        "ticker": ticker.upper(),
        "recommendation": recommendation,
        "last_price": round(last, 2),
        "entry_low": entry_low,
        "entry_high": entry_high,
        "take_profit": take_profit,
        "stop_loss": stop_loss,
        "rrr": rrr,
        "atr": round(a, 2),
        "support": idx.round_to_tick(support, "down") if support else None,
        "resistance": idx.round_to_tick(resistance, "up") if resistance else None,
        "pivot": {k: idx.round_to_tick(v, "nearest") for k, v in piv.items()},
        "ara": ara,
        "arb": arb,
        "max_stoploss_pct": settings.max_stoploss_pct,
    }
    return plan


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
