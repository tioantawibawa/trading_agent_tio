"""Agent 5 — Real-Time Intraday Monitor.

Berjalan selama jam bursa. Memantau harga saham pada trade plan aktif hari ini
serta posisi portofolio terbuka, lalu mengirim alert Telegram saat harga
menyentuh level Entry / Take Profit / Stop Loss.

Catatan: dengan data gratis (yfinance) harga delay ~15 menit — cocok untuk
swing/breakout, bukan scalping. Ganti provider ke GoAPI/RTI untuk realtime.
"""
from __future__ import annotations

from typing import Any

from src.config import settings
from src.core import database as dbm
from src.core import idx_rules as idx
from src.core.logging_conf import get_logger
from src.core.market_data import get_provider
from src.core.notifier import send_telegram

log = get_logger("agent5")

_HOURS = idx.TradingHours.from_strings(
    settings.session1_open, settings.session1_close,
    settings.session2_open, settings.session2_close,
)


def _rp(v: Any) -> str:
    return f"Rp{int(v):,}".replace(",", ".") if v is not None else "-"


async def _evaluate_plan(tk: str, plan: dict[str, Any], price: float) -> None:
    """Cek satu plan aktif terhadap harga terkini dan kirim alert bila perlu."""
    entry_low, entry_high = plan.get("entry_low"), plan.get("entry_high")
    tp, sl = plan.get("take_profit"), plan.get("stop_loss")

    if sl and price <= sl and not dbm.already_alerted_today(tk, "CUTLOSS"):
        msg = f"🔴 <b>[CUT LOSS ALERT]</b> {tk} menembus {_rp(sl)} (now {_rp(price)}). Disiplin eksekusi keluar."
        await send_telegram(msg)
        dbm.log_alert(tk, "CUTLOSS", price, msg)
    elif tp and price >= tp and not dbm.already_alerted_today(tk, "TP"):
        msg = f"🟢 <b>[TAKE PROFIT]</b> {tk} mencapai {_rp(tp)} (now {_rp(price)}). Pertimbangkan jual / trailing stop."
        await send_telegram(msg)
        dbm.log_alert(tk, "TP", price, msg)
    elif entry_low and entry_high and entry_low <= price <= entry_high \
            and not dbm.already_alerted_today(tk, "BUY"):
        msg = f"🔵 <b>[BUY SIGNAL]</b> {tk} di area beli {_rp(entry_low)}–{_rp(entry_high)} (now {_rp(price)})."
        await send_telegram(msg)
        dbm.log_alert(tk, "BUY", price, msg)


async def _evaluate_position(pos: dict[str, Any], price: float) -> None:
    """Alert untuk posisi portofolio terbuka berdasarkan batas P/L default."""
    tk = pos["ticker"]
    avg = pos.get("avg_price")
    if not avg:
        return
    change = (price - avg) / avg * 100
    if change <= -settings.max_stoploss_pct and not dbm.already_alerted_today(tk, "CUTLOSS"):
        msg = f"🔴 <b>[CUT LOSS — POSISI]</b> {tk} floating {change:.1f}% (avg {_rp(avg)}, now {_rp(price)})."
        await send_telegram(msg)
        dbm.log_alert(tk, "CUTLOSS", price, msg)


async def poll_once() -> int:
    """Satu siklus polling. Kembalikan jumlah ticker yang dievaluasi."""
    if not idx.is_market_open(_HOURS):
        log.debug("Pasar tutup — polling dilewati.")
        return 0

    provider = get_provider()
    plans = {p["ticker"]: p for p in dbm.get_active_plans() if p.get("stage") == "planned"}
    positions = {p["ticker"]: p for p in dbm.get_portfolio()}
    tickers = set(plans) | set(positions)

    for tk in tickers:
        price = provider.last_price(tk)
        if price is None:
            continue
        if tk in plans:
            await _evaluate_plan(tk, plans[tk], price)
        if tk in positions:
            await _evaluate_position(positions[tk], price)
    return len(tickers)


async def run_forever() -> None:
    """Loop polling untuk mode standalone (di luar orchestrator)."""
    import asyncio

    log.info("Agent 5 (Monitor) berjalan, interval %ss.", settings.monitor_poll_seconds)
    dbm.init_db()
    while True:
        try:
            n = await poll_once()
            log.debug("Polling selesai (%d ticker).", n)
        except Exception as exc:  # noqa: BLE001
            log.error("Kesalahan polling: %s", exc)
        await asyncio.sleep(settings.monitor_poll_seconds)


if __name__ == "__main__":
    import asyncio

    asyncio.run(run_forever())
