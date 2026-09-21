"""Uji aturan BEI: fraksi harga, pembulatan, ARA/ARB, jam bursa."""
from datetime import datetime
from zoneinfo import ZoneInfo

from src.core import idx_rules as idx

WIB = ZoneInfo("Asia/Jakarta")


def test_tick_size_bands():
    assert idx.tick_size(100) == 1
    assert idx.tick_size(200) == 2
    assert idx.tick_size(499) == 2
    assert idx.tick_size(500) == 5
    assert idx.tick_size(1999) == 5
    assert idx.tick_size(2000) == 10
    assert idx.tick_size(4999) == 10
    assert idx.tick_size(5000) == 25
    assert idx.tick_size(12345) == 25


def test_round_to_tick_modes():
    # 1460 di band tick 5 → sudah kelipatan 5.
    assert idx.round_to_tick(1462, "down") == 1460
    assert idx.round_to_tick(1462, "up") == 1465
    assert idx.round_to_tick(1462, "nearest") in (1460, 1465)
    # Band >= 5000 tick 25.
    assert idx.round_to_tick(5010, "down") == 5000
    assert idx.round_to_tick(5010, "up") == 5025


def test_ara_arb_symmetric_bands():
    # Harga acuan 100 (band <200 → 35%).
    assert idx.auto_rejection_pct(100) == 0.35
    # Harga acuan 1000 (band 200-5000 → 25%).
    assert idx.auto_rejection_pct(1000) == 0.25
    # Harga acuan 8000 (>5000 → 20%).
    assert idx.auto_rejection_pct(8000) == 0.20

    ara = idx.ara_price(1000)
    arb = idx.arb_price(1000)
    assert arb < 1000 < ara
    # ARA & ARB harus kelipatan tick yang valid.
    assert ara % idx.tick_size(ara) == 0
    assert arb % idx.tick_size(arb) == 0


def test_market_status():
    hours = idx.TradingHours.from_strings("09:00", "12:00", "13:30", "15:50")
    # Rabu 2026-09-23 pukul 10:00 WIB → sesi 1.
    assert idx.market_status(hours, datetime(2026, 9, 23, 10, 0, tzinfo=WIB)) == "session1"
    # 12:30 → istirahat.
    assert idx.market_status(hours, datetime(2026, 9, 23, 12, 30, tzinfo=WIB)) == "break"
    # 14:00 → sesi 2.
    assert idx.market_status(hours, datetime(2026, 9, 23, 14, 0, tzinfo=WIB)) == "session2"
    # 16:00 → tutup.
    assert idx.market_status(hours, datetime(2026, 9, 23, 16, 0, tzinfo=WIB)) == "closed"
    # Minggu → tutup.
    assert idx.market_status(hours, datetime(2026, 9, 20, 10, 0, tzinfo=WIB)) == "closed"
