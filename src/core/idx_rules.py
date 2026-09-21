"""Aturan spesifik Bursa Efek Indonesia (BEI/IDX).

Berisi logika deterministik yang dipakai Agent 3 (perencana kuantitatif):
- Fraksi harga (tick size) berjenjang.
- Auto Rejection Atas/Bawah (ARA/ARB) — simetris, berjenjang.
- Jam perdagangan (sesi 1 & 2) untuk mengetahui status pasar.

Catatan: aturan bursa dapat berubah dari waktu ke waktu. Nilai di sini
mencerminkan skema berjenjang yang umum dipakai dan mudah disesuaikan.
Sumber otoritatif tetap peraturan resmi IDX.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time
from zoneinfo import ZoneInfo

WIB = ZoneInfo("Asia/Jakarta")

# --- Fraksi harga (tick size) berdasarkan rentang harga (Rp) ---
# (batas_bawah_inklusif, tick)
_TICK_TABLE: list[tuple[float, int]] = [
    (0, 1),        # < 200
    (200, 2),      # 200 – < 500
    (500, 5),      # 500 – < 2000
    (2000, 10),    # 2000 – < 5000
    (5000, 25),    # >= 5000
]
_TICK_UPPER = [200, 500, 2000, 5000, float("inf")]


def tick_size(price: float) -> int:
    """Kembalikan fraksi harga (tick) yang berlaku untuk sebuah harga."""
    for (lower, tick), upper in zip(_TICK_TABLE, _TICK_UPPER):
        if lower <= price < upper:
            return tick
    return _TICK_TABLE[-1][1]


def round_to_tick(price: float, mode: str = "nearest") -> int:
    """Bulatkan harga ke kelipatan fraksi harga yang valid di BEI.

    mode: 'nearest' | 'down' (untuk entry/support) | 'up' (untuk resistance/TP).
    """
    if price <= 0:
        return 0
    tick = tick_size(price)
    q = price / tick
    if mode == "down":
        n = int(q)  # floor
    elif mode == "up":
        n = int(q) if q == int(q) else int(q) + 1
    else:
        n = int(q + 0.5)
    return int(n * tick)


# --- Auto Rejection (ARA/ARB), simetris & berjenjang ---
# (harga_atas_eksklusif, persentase)
_AR_TABLE: list[tuple[float, float]] = [
    (200, 0.35),          # Rp50 – Rp200  -> 35%
    (5000, 0.25),         # Rp200 – Rp5000 -> 25%
    (float("inf"), 0.20), # > Rp5000 -> 20%
]


def auto_rejection_pct(prev_close: float) -> float:
    """Persentase batas ARA/ARB simetris berdasarkan harga acuan."""
    for upper, pct in _AR_TABLE:
        if prev_close < upper:
            return pct
    return _AR_TABLE[-1][1]


def ara_price(prev_close: float) -> int:
    """Batas Auto Rejection Atas (harga tertinggi yang diperbolehkan)."""
    pct = auto_rejection_pct(prev_close)
    return round_to_tick(prev_close * (1 + pct), mode="down")


def arb_price(prev_close: float) -> int:
    """Batas Auto Rejection Bawah (harga terendah yang diperbolehkan)."""
    pct = auto_rejection_pct(prev_close)
    return round_to_tick(prev_close * (1 - pct), mode="up")


# --- Jam perdagangan ---
@dataclass(frozen=True)
class TradingHours:
    session1_open: time
    session1_close: time
    session2_open: time
    session2_close: time

    @staticmethod
    def _parse(hhmm: str) -> time:
        h, m = hhmm.split(":")
        return time(int(h), int(m))

    @classmethod
    def from_strings(
        cls, s1o: str, s1c: str, s2o: str, s2c: str
    ) -> "TradingHours":
        return cls(
            cls._parse(s1o), cls._parse(s1c),
            cls._parse(s2o), cls._parse(s2c),
        )


def is_trading_day(d: date) -> bool:
    """Hari bursa = Senin–Jumat. (Hari libur nasional belum ditangani —
    tambahkan kalender libur BEI bila perlu.)"""
    return d.weekday() < 5


def market_status(hours: TradingHours, now: datetime | None = None) -> str:
    """Kembalikan status pasar: 'pre_open' | 'session1' | 'break' |
    'session2' | 'closed'."""
    now = now or datetime.now(WIB)
    if not is_trading_day(now.date()):
        return "closed"
    t = now.timetz().replace(tzinfo=None)
    if t < hours.session1_open:
        return "pre_open"
    if hours.session1_open <= t < hours.session1_close:
        return "session1"
    if hours.session1_close <= t < hours.session2_open:
        return "break"
    if hours.session2_open <= t < hours.session2_close:
        return "session2"
    return "closed"


def is_market_open(hours: TradingHours, now: datetime | None = None) -> bool:
    return market_status(hours, now) in {"session1", "session2"}
