"""Agent 5 — Real-Time Intraday Monitor.

Berjalan selama jam bursa. Memantau harga saham pada trade plan aktif hari ini
serta posisi portofolio terbuka, lalu mengirim alert Telegram saat harga
menyentuh level Entry / Take Profit / Stop Loss.

Juga menjalankan EARLY WARNING: mendeteksi lonjakan harga mendadak (spike) pada
watchlist/portofolio dan mengirim notifikasi proaktif secara otomatis.

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
    """Alert posisi portofolio: TP saat mencapai target profit, CUTLOSS saat
    menyentuh stop. Selalu aktif selama monitor jalan (jam bursa)."""
    tk = pos["ticker"]
    avg = pos.get("avg_price")
    target = pos.get("target_price")
    stop = pos.get("stop_price")
    change = ((price - avg) / avg * 100) if avg else None

    # 1) Target profit tercapai.
    if target and price >= target and not dbm.already_alerted_today(tk, "TP"):
        pl = f" (floating {change:+.1f}%)" if change is not None else ""
        msg = (f"🟢 <b>[TARGET PROFIT — POSISI]</b> {tk} menyentuh target {_rp(target)} "
               f"(now {_rp(price)}){pl}. Pertimbangkan realisasi profit / trailing stop.")
        await send_telegram(msg)
        dbm.log_alert(tk, "TP", price, msg)
        return

    # 2) Stop / cut-loss tersentuh (pakai stop_price bila ada, else batas persen).
    hit_stop = (stop and price <= stop) or (
        change is not None and change <= -settings.max_stoploss_pct)
    if hit_stop and not dbm.already_alerted_today(tk, "CUTLOSS"):
        ref = _rp(stop) if stop else f"{-settings.max_stoploss_pct:.0f}%"
        pl = f" (floating {change:+.1f}%)" if change is not None else ""
        msg = (f"🔴 <b>[CUT LOSS — POSISI]</b> {tk} menembus batas {ref} "
               f"(now {_rp(price)}){pl}. Disiplin eksekusi keluar.")
        await send_telegram(msg)
        dbm.log_alert(tk, "CUTLOSS", price, msg)


from collections import deque

# Riwayat harga singkat per ticker (sliding window) untuk deteksi lonjakan.
# {ticker: deque[(epoch_detik, harga)]}
_spike_hist: dict[str, deque] = {}

# Heartbeat: cetak log INFO tiap N poll (~ N menit) agar mudah diverifikasi.
_poll_count = 0
_HEARTBEAT_EVERY = 15


def _context_notes(tk: str, price: float) -> tuple[str, float | None]:
    """Catatan konteks untuk alert spike: gain harian & apakah ramai berita."""
    daily = dbm.get_daily_data(tk) or {}
    prev_close = daily.get("prev_close")
    day_gain = ((price - prev_close) / prev_close * 100) if prev_close else None
    notes = []
    volumes = daily.get("volumes") or []
    if len(volumes) >= settings.volume_lookback_days + 1:
        avg = sum(volumes[-(settings.volume_lookback_days + 1):-1]) / settings.volume_lookback_days
        if avg and volumes[-1] >= avg * settings.volume_spike_multiplier:
            notes.append(f"volume {volumes[-1]/avg:.1f}x rata-rata")
    sentiment = dbm.get_sentiment() or {}
    if tk in (sentiment.get("top_mentions") or {}):
        notes.append("ramai diberitakan")
    return ("; ".join(notes), day_gain)


async def _scan_spikes(price_map: dict[str, float], tickers: set[str]) -> int:
    """Early warning: deteksi kenaikan mendadak (kenaikan dari titik terendah
    dalam jendela geser) & kirim alert proaktif. Kembalikan jumlah spike."""
    if not settings.early_warning:
        return 0
    import time

    now = time.time()
    window_s = settings.early_warning_window_min * 60
    spikes = 0
    for tk in tickers:
        price = price_map.get(tk)
        if price is None or price <= 0:
            continue
        hist = _spike_hist.setdefault(tk, deque(maxlen=600))
        hist.append((now, price))
        # Buang sampel di luar jendela.
        while hist and now - hist[0][0] > window_s:
            hist.popleft()
        if len(hist) < 2:
            continue
        # Kenaikan dari harga TERENDAH dalam jendela (deteksi rebound/spike).
        low_t, low_p = min(hist, key=lambda s: s[1])
        pct = (price - low_p) / low_p * 100 if low_p else 0.0
        if pct < settings.early_warning_pct:
            continue
        # Cooldown agar tidak spam.
        last = dbm.minutes_since_last_alert(tk, "SPIKE")
        if last is not None and last < settings.early_warning_cooldown_min:
            continue
        notes, day_gain = _context_notes(tk, price)
        extra = f" | hari ini {day_gain:+.1f}%" if day_gain is not None else ""
        if notes:
            extra += f" | {notes}"
        mins = max(1, int((now - low_t) / 60))
        msg = (f"🚨 <b>[EARLY WARNING — SPIKE]</b> {tk} melonjak "
               f"<b>+{pct:.1f}%</b> dalam ~{mins} menit (now {_rp(price)}){extra}. "
               f"Potensi momentum — cek peluang.")
        await send_telegram(msg)
        dbm.log_alert(tk, "SPIKE", price, msg)
        log.info("SPIKE terdeteksi: %s +%.1f%% (%s)", tk, pct, _rp(price))
        spikes += 1
    return spikes


async def poll_once() -> int:
    """Satu siklus polling. Kembalikan jumlah ticker yang dievaluasi."""
    if not idx.is_market_open(_HOURS):
        log.debug("Pasar tutup — polling dilewati.")
        return 0

    provider = get_provider()
    plans = {p["ticker"]: p for p in dbm.get_active_plans() if p.get("stage") == "planned"}
    positions = {p["ticker"]: p for p in dbm.get_portfolio()}
    watch = set(dbm.get_watchlist())
    eval_tickers = set(plans) | set(positions)
    all_tickers = eval_tickers | watch  # termasuk LQ45 bila dimuat ke watchlist

    # Ambil harga SEKALI per saham (dipakai ulang untuk evaluasi & scan spike).
    price_map: dict[str, float] = {}
    for tk in all_tickers:
        p = provider.last_price(tk)
        if p is not None:
            price_map[tk] = p

    for tk in eval_tickers:
        price = price_map.get(tk)
        if price is None:
            continue
        if tk in plans:
            await _evaluate_plan(tk, plans[tk], price)
        if tk in positions:
            await _evaluate_position(positions[tk], price)

    # Early warning dipindai untuk seluruh watchlist + plan + posisi.
    spikes = await _scan_spikes(price_map, all_tickers)

    # Heartbeat berkala agar mudah diverifikasi monitor benar-benar berjalan.
    global _poll_count
    _poll_count += 1
    if _poll_count % _HEARTBEAT_EVERY == 1 or spikes:
        log.info("Monitor aktif: %d saham dipantau (harga OK: %d), %d spike.",
                 len(all_tickers), len(price_map), spikes)
    return len(all_tickers)


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
