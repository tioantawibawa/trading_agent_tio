"""Uji indikator deterministik."""
from src.core import indicators as ind


def test_atr_basic():
    highs = [10, 11, 12, 13, 14, 15]
    lows = [9, 10, 11, 12, 13, 14]
    closes = [9.5, 10.5, 11.5, 12.5, 13.5, 14.5]
    a = ind.atr(highs, lows, closes, period=3)
    assert a is not None and a > 0


def test_volume_spike_detected():
    vols = [100] * 20 + [500]  # 21 nilai, terakhir 5x rata-rata
    res = ind.volume_spike(vols, multiplier=2.0, lookback=20)
    assert res["is_spike"] is True
    assert res["ratio"] == 5.0


def test_volume_spike_none_when_flat():
    vols = [100] * 21
    res = ind.volume_spike(vols, multiplier=2.0, lookback=20)
    assert res["is_spike"] is False


def test_support_resistance():
    highs = [10, 12, 11, 15, 13]
    lows = [8, 9, 7, 10, 9]
    s, r = ind.recent_support_resistance(highs, lows, lookback=5)
    assert s == 7
    assert r == 15


def test_pivot_points():
    p = ind.pivot_points(110, 90, 100)
    assert p["pivot"] == 100
    assert p["r1"] > p["pivot"] > p["s1"]
